// SPDX-License-Identifier: GPL-2.0-only
/*
 * CI-only lifecycle test. This is not a D2365 hardware emulator.
 * The poweroff and GPIO drivers are compiled unchanged. The real OF,
 * platform bus, device links, devres and power-supply core do the work.
 * Only register storage, the parent IRQ and the supply are synthetic.
 * No sys-off callback is invoked.
 */
#include <kunit/test.h>
#include <linux/completion.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/gpio/apple-d2365.h>
#include <linux/irq.h>
#include <linux/irq_sim.h>
#include <linux/kthread.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/power_supply.h>
#include <linux/regmap.h>
#include <linux/sched.h>
#include <linux/tracepoint.h>
#include "../../base/trace.h"

struct fixture {
	struct kunit *test;
	struct of_changeset changes, properties;
	struct device_node *nodes[4];
	struct platform_device *parent, *gpio, *supply, *power, *blocker;
	struct regmap *map;
	struct irq_domain *domain;
	unsigned int irq;
	struct power_supply *psy;
	struct device *target;
	struct task_struct *thread;
	struct completion entered, release, done;
	bool applied, properties_applied, supply_driver, blocker_driver, tracing;
	bool pause_remove;
	atomic_t sys_add, sys_rel, psy_rel, provider_add, provider_rel;
	atomic_t nr_release;
	int release_order[16];
	unsigned int supply_removes, forbidden_access;
	u8 registers[0x5010];
};

static void trace_devres(void *data, struct device *dev, const char *op,
			 void *node, const char *name, size_t size)
{
	struct fixture *f = data;
	int kind = 0, i;

	if (!f->power || dev != &f->power->dev || !name)
		return;
	if (!strcmp(name, "devm_unregister_sys_off_handler")) {
		if (!strcmp(op, "ADD"))
			atomic_inc(&f->sys_add);
		if (!strcmp(op, "REL")) {
			atomic_inc(&f->sys_rel);
			kind = 1;
		}
	} else if (!strcmp(name, "devm_power_supply_put")) {
		if (!strcmp(op, "REL")) {
			atomic_inc(&f->psy_rel);
			kind = 2;
		}
	} else if (!strcmp(name, "apple_d2365_device_put")) {
		if (!strcmp(op, "ADD"))
			atomic_inc(&f->provider_add);
		if (!strcmp(op, "REL")) {
			atomic_inc(&f->provider_rel);
			kind = 3;
		}
	}
	if (kind) {
		i = atomic_fetch_inc(&f->nr_release);
		if (i < ARRAY_SIZE(f->release_order))
			WRITE_ONCE(f->release_order[i], kind);
	}
}

static void reset_trace(struct fixture *f)
{
	atomic_set(&f->sys_add, 0);
	atomic_set(&f->sys_rel, 0);
	atomic_set(&f->psy_rel, 0);
	atomic_set(&f->provider_add, 0);
	atomic_set(&f->provider_rel, 0);
	atomic_set(&f->nr_release, 0);
	memset(f->release_order, 0, sizeof(f->release_order));
}

static bool bound(struct device *dev)
{
	bool result;

	device_lock(dev);
	result = device_is_bound(dev);
	device_unlock(dev);
	return result;
}

static int register_read(void *data, unsigned int reg, unsigned int *value)
{
	struct fixture *f = data;

	if (reg >= ARRAY_SIZE(f->registers))
		return -EINVAL;
	if (reg == 0x0400 || reg >= 0x5000)
		f->forbidden_access++;
	*value = f->registers[reg];
	return 0;
}

static int register_write(void *data, unsigned int reg, unsigned int value)
{
	struct fixture *f = data;

	if (reg >= ARRAY_SIZE(f->registers))
		return -EINVAL;
	if (reg == 0x0400 || reg >= 0x5000)
		f->forbidden_access++;
	f->registers[reg] = value;
	return 0;
}

static const struct regmap_config test_regmap = {
	.reg_bits = 16,
	.val_bits = 8,
	.max_register = 0x500f,
	.reg_read = register_read,
	.reg_write = register_write,
	.cache_type = REGCACHE_NONE,
};

static enum power_supply_property test_properties[] = {
	POWER_SUPPLY_PROP_ONLINE,
};

static int supply_property(struct power_supply *psy,
			   enum power_supply_property property,
			   union power_supply_propval *value)
{
	u32 *state = power_supply_get_drvdata(psy);

	if (property != POWER_SUPPLY_PROP_ONLINE || *state != 0x2365)
		return -EINVAL;
	value->intval = 0;
	return 0;
}

static const struct power_supply_desc supply_desc = {
	.name = "d2365-lifetime-test-supply",
	.type = POWER_SUPPLY_TYPE_MAINS,
	.properties = test_properties,
	.num_properties = ARRAY_SIZE(test_properties),
	.get_property = supply_property,
};

static int supply_probe(struct platform_device *pdev)
{
	struct fixture *f = dev_get_drvdata(pdev->dev.parent);
	struct power_supply_config config = {};
	u32 *state;

	state = devm_kzalloc(&pdev->dev, sizeof(*state), GFP_KERNEL);
	if (!state)
		return -ENOMEM;
	*state = 0x2365;
	config.drv_data = state;
	config.fwnode = dev_fwnode(&pdev->dev);
	f->psy = devm_power_supply_register(&pdev->dev, &supply_desc, &config);
	return PTR_ERR_OR_ZERO(f->psy);
}

static void supply_remove(struct platform_device *pdev)
{
	struct fixture *f = dev_get_drvdata(pdev->dev.parent);

	/* The consumer's devres callbacks completed before this callback. */
	if (f->power)
		KUNIT_EXPECT_PTR_EQ(f->test, READ_ONCE(f->power->dev.driver), NULL);
	KUNIT_EXPECT_EQ(f->test, atomic_read(&f->psy->use_cnt), 1);
	f->supply_removes++;
	f->psy = NULL;
}

static struct platform_driver supply_driver = {
	.probe = supply_probe,
	.remove = supply_remove,
	.driver.name = "d2365-test-supply",
};

static int blocker_probe(struct platform_device *pdev)
{
	struct fixture *f = dev_get_drvdata(pdev->dev.parent);

	return device_link_add(&pdev->dev, f->target,
			       DL_FLAG_AUTOREMOVE_CONSUMER) ? 0 : -EINVAL;
}

static void blocker_remove(struct platform_device *pdev)
{
	struct fixture *f = dev_get_drvdata(pdev->dev.parent);

	if (!READ_ONCE(f->pause_remove))
		return;
	complete(&f->entered);
	/* Bounded even if a test assertion aborts before releasing us. */
	if (!wait_for_completion_timeout(&f->release, 30 * HZ))
		KUNIT_FAIL(f->test, "blocker removal timed out");
}

static struct platform_driver blocker_driver = {
	.probe = blocker_probe,
	.remove = blocker_remove,
	.driver.name = "d2365-test-blocker",
};

static int add_device(struct fixture *f, struct platform_device **slot,
		      const char *name, struct device_node *node, bool irq)
{
	struct platform_device *pdev;
	int ret;

	pdev = platform_device_alloc(name, PLATFORM_DEVID_NONE);
	if (!pdev)
		return -ENOMEM;
	pdev->dev.parent = f->parent ? &f->parent->dev : NULL;
	if (node)
		device_set_node(&pdev->dev, of_fwnode_handle(of_node_get(node)));
	if (irq) {
		struct resource resource = DEFINE_RES_IRQ(f->irq);

		ret = platform_device_add_resources(pdev, &resource, 1);
		if (ret)
			goto put;
	}
	/* Observe devres allocations made by the synchronous probe. */
	*slot = pdev;
	ret = platform_device_add(pdev);
	if (!ret)
		return 0;
	*slot = NULL;
put:
	platform_device_put(pdev);
	return ret;
}

static int unbind_thread(void *data)
{
	struct fixture *f = data;

	device_release_driver(f->target);
	complete(&f->done);
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
	return 0;
}

static void cleanup(void *data)
{
	struct fixture *f = data;
	int i;

	WRITE_ONCE(f->pause_remove, false);
	complete_all(&f->release);
	if (f->thread) {
		kthread_stop(f->thread);
		f->thread = NULL;
	}
	if (f->blocker)
		platform_device_unregister(f->blocker);
	if (f->power) {
		platform_device_unregister(f->power);
		f->power = NULL;
	}
	if (f->supply)
		platform_device_unregister(f->supply);
	if (f->gpio)
		platform_device_unregister(f->gpio);
	if (f->tracing) {
		unregister_trace_devres_log(trace_devres, f);
		tracepoint_synchronize_unregister();
	}
	if (f->blocker_driver)
		platform_driver_unregister(&blocker_driver);
	if (f->supply_driver)
		platform_driver_unregister(&supply_driver);
	if (f->irq)
		irq_dispose_mapping(f->irq);
	if (f->domain)
		irq_domain_remove_sim(f->domain);
	if (f->map)
		regmap_exit(f->map);
	if (f->parent)
		platform_device_unregister(f->parent);
	if (f->applied)
		KUNIT_EXPECT_EQ(f->test, of_changeset_revert(&f->changes), 0);
	if (f->properties_applied)
		KUNIT_EXPECT_EQ(f->test, of_changeset_revert(&f->properties), 0);
	of_changeset_destroy(&f->changes);
	of_changeset_destroy(&f->properties);
	for (i = ARRAY_SIZE(f->nodes) - 1; i >= 0; i--)
		of_node_put(f->nodes[i]);
}

static void expect_bound(struct kunit *test, struct fixture *f)
{
	KUNIT_ASSERT_TRUE(test, bound(&f->gpio->dev));
	KUNIT_ASSERT_TRUE(test, apple_d2365_gpio_events_ready(&f->gpio->dev));
	KUNIT_ASSERT_TRUE(test, bound(&f->supply->dev));
	KUNIT_ASSERT_TRUE(test, bound(&f->power->dev));
	KUNIT_ASSERT_NOT_ERR_OR_NULL(test, f->psy);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->psy->use_cnt), 2);
}

static void expect_released(struct kunit *test, struct fixture *f)
{
	int i;

	KUNIT_EXPECT_FALSE(test, bound(&f->power->dev));
	KUNIT_EXPECT_EQ(test, atomic_read(&f->sys_rel), 3);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->psy_rel), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->provider_rel), 2);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->nr_release), 6);
	for (i = 0; i < 3; i++)
		KUNIT_EXPECT_EQ(test, f->release_order[i], 1);
	KUNIT_EXPECT_EQ(test, f->release_order[3], 2);
	KUNIT_EXPECT_EQ(test, f->release_order[4], 3);
	KUNIT_EXPECT_EQ(test, f->release_order[5], 3);
}

static void race(struct kunit *test, struct fixture *f, bool supply)
{
	struct device *target = supply ? &f->supply->dev : &f->gpio->dev;
	int ret;

	device_release_driver(&f->power->dev);
	f->target = target;
	reinit_completion(&f->entered);
	reinit_completion(&f->release);
	reinit_completion(&f->done);
	WRITE_ONCE(f->pause_remove, true);
	KUNIT_ASSERT_EQ(test, add_device(f, &f->blocker,
				       "d2365-test-blocker", NULL, false), 0);
	KUNIT_ASSERT_TRUE(test, bound(&f->blocker->dev));
	f->thread = kthread_run(unbind_thread, f, "d2365-unbind");
	if (IS_ERR(f->thread)) {
		f->thread = NULL;
		KUNIT_FAIL(test, "cannot start unbind thread");
		return;
	}
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->entered, 10 * HZ), 0UL);
	device_lock(target);
	KUNIT_EXPECT_TRUE(test, device_is_bound(target));
	KUNIT_EXPECT_EQ(test, target->links.status, DL_DEV_UNBINDING);
	device_unlock(target);
	reset_trace(f);
	ret = device_attach(&f->power->dev);
	KUNIT_EXPECT_LE(test, ret, 0);
	KUNIT_EXPECT_FALSE(test, bound(&f->power->dev));
	/* Named devres actions prove that the actual helpers were entered. */
	KUNIT_EXPECT_EQ(test, atomic_read(&f->provider_add), supply ? 2 : 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->provider_rel), supply ? 2 : 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->sys_add), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->psy->use_cnt), 1);
	complete_all(&f->release);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->done, 10 * HZ), 0UL);
	kthread_stop(f->thread);
	f->thread = NULL;
	WRITE_ONCE(f->pause_remove, false);
	platform_device_unregister(f->blocker);
	f->blocker = NULL;
	KUNIT_EXPECT_FALSE(test, bound(target));
	KUNIT_ASSERT_GE(test, device_attach(target), 0);
	KUNIT_ASSERT_GE(test, device_attach(&f->power->dev), 0);
	expect_bound(test, f);
	kunit_info(test, "real %s already-unbinding probe rejected and rebound\n",
		   supply ? "supply" : "GPIO");
}

static void d2365_supplier_lifetime(struct kunit *test)
{
	struct fixture *f;
	struct device_node *existing;
	const u32 phandle = 0x7f236501;
	int i, ret;

	f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, f);
	f->test = test;
	of_changeset_init(&f->changes);
	of_changeset_init(&f->properties);
	init_completion(&f->entered);
	init_completion(&f->release);
	init_completion(&f->done);
	KUNIT_ASSERT_EQ(test, kunit_add_action_or_reset(test, cleanup, f), 0);
	KUNIT_ASSERT_NOT_NULL(test, of_root);
	existing = of_find_node_by_phandle(phandle);
	if (existing) {
		of_node_put(existing);
		KUNIT_FAIL(test, "test phandle already in use");
		return;
	}
	f->nodes[0] = of_changeset_create_node(&f->changes, of_root,
					     "d2365-lifetime-test");
	KUNIT_ASSERT_NOT_NULL(test, f->nodes[0]);
	KUNIT_ASSERT_EQ(test, of_changeset_add_prop_string(&f->properties,
		f->nodes[0], "status", "disabled"), 0);
	f->nodes[1] = of_changeset_create_node(&f->changes, f->nodes[0], "gpio");
	f->nodes[2] = of_changeset_create_node(&f->changes, f->nodes[0], "supply");
	f->nodes[3] = of_changeset_create_node(&f->changes, f->nodes[0], "poweroff");
	for (i = 1; i < 4; i++)
		KUNIT_ASSERT_NOT_NULL(test, f->nodes[i]);
	KUNIT_ASSERT_EQ(test, of_changeset_add_prop_string(&f->properties,
		f->nodes[1], "compatible", "apple,d2365-pmic-gpio"), 0);
	KUNIT_ASSERT_EQ(test, of_changeset_add_prop_bool(&f->properties,
		f->nodes[1], "interrupt-controller"), 0);
	KUNIT_ASSERT_EQ(test, of_changeset_add_prop_u32(&f->properties,
		f->nodes[1], "#interrupt-cells", 2), 0);
	KUNIT_ASSERT_EQ(test, of_changeset_add_prop_bool(&f->properties,
		f->nodes[1], "gpio-controller"), 0);
	KUNIT_ASSERT_EQ(test, of_changeset_add_prop_u32(&f->properties,
		f->nodes[1], "#gpio-cells", 2), 0);
	KUNIT_ASSERT_EQ(test, of_changeset_add_prop_u32(&f->properties,
		f->nodes[2], "phandle", phandle), 0);
	KUNIT_ASSERT_EQ(test, of_changeset_add_prop_string(&f->properties,
		f->nodes[3], "compatible", "apple,d2365-poweroff"), 0);
	KUNIT_ASSERT_EQ(test, of_changeset_add_prop_u32(&f->properties,
		f->nodes[3], "power-supplies", phandle), 0);
	/* Populate detached nodes before ATTACH derives the phandle. */
	KUNIT_ASSERT_EQ(test, of_changeset_apply(&f->properties), 0);
	f->properties_applied = true;
	KUNIT_ASSERT_EQ(test, of_changeset_apply(&f->changes), 0);
	f->applied = true;
	existing = of_find_node_by_phandle(phandle);
	KUNIT_EXPECT_PTR_EQ(test, existing, f->nodes[2]);
	of_node_put(existing);
	KUNIT_ASSERT_EQ(test, add_device(f, &f->parent,
				       "d2365-test-parent", f->nodes[0], false), 0);
	platform_set_drvdata(f->parent, f);
	f->map = regmap_init(&f->parent->dev, NULL, f, &test_regmap);
	if (IS_ERR(f->map)) {
		ret = PTR_ERR(f->map);
		f->map = NULL;
		KUNIT_FAIL(test, "regmap_init: %d", ret);
		return;
	}
	f->domain = irq_domain_create_sim(NULL, 1);
	if (IS_ERR(f->domain)) {
		f->domain = NULL;
		KUNIT_FAIL(test, "irq_domain_create_sim failed");
		return;
	}
	KUNIT_ASSERT_NOT_NULL(test, f->domain);
	f->irq = irq_create_mapping(f->domain, 0);
	KUNIT_ASSERT_NE(test, f->irq, 0U);
	KUNIT_ASSERT_EQ(test, irq_set_irq_type(f->irq, IRQ_TYPE_EDGE_RISING), 0);
	KUNIT_ASSERT_EQ(test, platform_driver_register(&supply_driver), 0);
	f->supply_driver = true;
	KUNIT_ASSERT_EQ(test, platform_driver_register(&blocker_driver), 0);
	f->blocker_driver = true;
	KUNIT_ASSERT_EQ(test, register_trace_devres_log(trace_devres, f), 0);
	f->tracing = true;
	KUNIT_ASSERT_EQ(test, add_device(f, &f->gpio,
				       "d2365-test-gpio", f->nodes[1], true), 0);
	KUNIT_ASSERT_EQ(test, add_device(f, &f->supply,
				       "d2365-test-supply", f->nodes[2], false), 0);
	KUNIT_ASSERT_EQ(test, add_device(f, &f->power,
				       "d2365-test-power", f->nodes[3], false), 0);
	expect_bound(test, f);
	KUNIT_ASSERT_EQ(test, atomic_read(&f->sys_add), 3);

	for (i = 0; i < 3; i++) {
		reset_trace(f);
		device_release_driver(&f->supply->dev);
		expect_released(test, f);
		KUNIT_ASSERT_GE(test, device_attach(&f->supply->dev), 0);
		KUNIT_ASSERT_GE(test, device_attach(&f->power->dev), 0);
		expect_bound(test, f);
	}
	reset_trace(f);
	device_release_driver(&f->gpio->dev);
	expect_released(test, f);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->psy->use_cnt), 1);
	KUNIT_ASSERT_GE(test, device_attach(&f->gpio->dev), 0);
	KUNIT_ASSERT_GE(test, device_attach(&f->power->dev), 0);
	expect_bound(test, f);
	kunit_info(test, "three supply and one GPIO unbind/rebind cycles passed; sys-off release precedes supply/provider release\n");

	/*
	 * In permissive mode an inferred SYNC_STATE_ONLY supply link can be
	 * upgraded to CONSUMER_PROBE before probe, legitimately protecting
	 * an in-flight probe. Test rejection with fw_devlink=off instead.
	 */
	if (!strstr(saved_command_line, "fw_devlink=permissive"))
		race(test, f, true);
	race(test, f, false);
	KUNIT_EXPECT_EQ(test, f->forbidden_access, 0U);
	KUNIT_EXPECT_GE(test, f->supply_removes, 3U);
}

static struct kunit_case lifetime_cases[] = {
	KUNIT_CASE(d2365_supplier_lifetime),
	{}
};

static struct kunit_suite lifetime_suite = {
	.name = "d2365-supplier-lifetime",
	.test_cases = lifetime_cases,
};
kunit_test_suite(lifetime_suite);
MODULE_LICENSE("GPL");
