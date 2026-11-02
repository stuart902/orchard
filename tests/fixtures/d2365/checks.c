/* SPDX-License-Identifier: MIT */
static struct apple_d2365_poweroff pmic;
static struct sys_off_data off = { &pmic };
static void reset(void)
{
    memset(memory, 0, sizeof(memory));
    memset(operations, 0, sizeof(operations));
    count = fail_at = source_reads = online_reads = 0;
    standby_attempts = standby_writes = restart_calls = sleeps = 0;
    source_change_at = online_change_at = final_event_change = 0;
    source_value = online_value = 0;
    final_phase = false;
    pmic = (struct apple_d2365_poweroff){ .data = &apple_d2365_data, .restart = true };
    memory[0x0400] = 0xa4;
    memory[0x500f] = 0xff;
    for (unsigned i = 0; i < 18; i++) {
        memory[0x0900 + 2 * i] = i % 2 ? 0x81 : 0x3f;
        memory[0x0901 + 2 * i] = 0x80 + i;
    }
    for (unsigned i = 0; i < 6; i++) memory[0x0929 + 6 * i] = i % 2 ? 0xff : 0x01;
}
static void prepare(void) { assert(apple_d2365_poweroff_prepare(&off) == NOTIFY_DONE); }
static void rejected(void)
{
    assert(pmic.restart && !pmic.standby_requested);
    assert(!standby_writes && !sleeps);
}
static unsigned find(char kind, unsigned reg)
{
    for (unsigned i = 0; i < count; i++)
        if (operations[i].kind == kind && operations[i].reg == reg) return i;
    assert(!"missing operation");
    return 0;
}
static void check_order(void)
{
    reset(); prepare();
    assert(!pmic.restart && pmic.standby_requested);
    assert(standby_writes == 1 && sleeps == 1);
    assert(memory[0x0400] == 0xa5 && memory[0x500f] == 0x27);
    unsigned events = find('R', 0x0140), mask = find('W', 0x01c0);
    unsigned rtc = find('w', 0x0500), state = find('w', 0x5001);
    unsigned flags = find('w', 0x5003), boot = find('w', 0x500f);
    unsigned gpio = find('W', 0x0900), standby = find('w', 0x0400);
    assert(events < mask && mask < rtc && rtc < state && state < flags);
    assert(flags < boot && boot < gpio && gpio < standby);
    assert(operations[events].size == 30 && operations[mask].size == 30);
    assert(!memcmp(memory + 0x01c0, apple_d2365_data.event_mask, 30));
    assert(memory[0x0500] == 1 && !memory[0x5001] && !memory[0x5003]);
    unsigned event_count = 0, last_events = 0;
    for (unsigned i = 0; i < count; i++) {
        if (operations[i].reg == 0x0140) {
            assert(operations[i].kind == 'R' && operations[i].size == 30);
            event_count++; last_events = i;
        }
    }
    assert(event_count == 2 && last_events > gpio && last_events < standby);
    assert(source_reads >= 2 && online_reads >= 2);
    /* Request must be forced, not optimized away when the bit is already set. */
    reset(); memory[0x0400] = 0xa5; prepare();
    assert(standby_writes == 1 && memory[0x0400] == 0xa5);
}
static void check_gpio(void)
{
    for (unsigned value = 0; value < 256; value++) {
        reset();
        for (unsigned i = 0; i < 18; i++) memory[0x0900 + 2 * i] = value;
        for (unsigned i = 0; i < 6; i++) memory[0x0929 + 6 * i] = value;
        prepare();
        unsigned expected = value <= 0x3f ? value & ~1U : value;
        assert(pmic.standby_requested);
        for (unsigned i = 0; i < 18; i++) {
            assert(memory[0x0900 + 2 * i] == expected);
            assert(memory[0x0901 + 2 * i] == 0x80 + i);
        }
        for (unsigned i = 0; i < 6; i++) assert(memory[0x0929 + 6 * i] == expected);
    }
}
static void check_sources(void)
{
    for (unsigned value = 1; value < 256; value++) {
        reset(); source_value = value; prepare(); rejected();
        assert(memory[0x500f] == 0xb7 && !standby_attempts);
    }
    const int online[] = {1, 2, -1};
    for (unsigned i = 0; i < ARRAY_SIZE(online); i++) {
        reset(); online_value = online[i]; prepare(); rejected();
        assert(memory[0x500f] == 0xb7);
    }
    reset(); fail_at = 1; prepare(); rejected(); /* Unknown supply. */
    assert(count == 1);
    reset(); fail_at = 2; prepare(); rejected(); /* Unknown live status. */
    assert(count == 2);
}
static void check_changes(void)
{
    reset(); source_change_at = 2; prepare(); rejected();
    assert(memory[0x500f] == 0xb7);
    reset(); online_change_at = 2; prepare(); rejected();
    assert(memory[0x500f] == 0xb7);
    /* Attach immediately after GPIO preparation and the final event read. */
    reset(); final_event_change = 1; prepare(); rejected();
    assert(memory[0x500f] == 0xb7 && !standby_attempts);
}
static void failure_route(unsigned route)
{
    if (route == 1) source_value = 1;
    if (route == 2) source_change_at = 2;
    if (route == 3) final_event_change = 1;
    if (route == 4) online_change_at = 2;
}
static void check_failures(void)
{
    for (unsigned route = 0; route < 5; route++) {
        reset(); failure_route(route); prepare();
        unsigned total = count;
        assert(total > 5);
        for (unsigned failure = 1; failure <= total; failure++) {
            reset(); failure_route(route); fail_at = failure; prepare(); rejected();
            assert(count == failure); /* No I/O follows a failed transaction. */
            assert(standby_attempts == (route == 0 && failure == total));
        }
    }
}
static void check_final(void)
{
    reset(); prepare();
    unsigned before = count;
    final_phase = true;
    assert(apple_d2365_poweroff_final(&off) == NOTIFY_DONE);
    assert(count == before && !restart_calls && sleeps == 1);
    reset(); source_value = 1; prepare();
    before = count; final_phase = true;
    assert(apple_d2365_poweroff_final(&off) == NOTIFY_DONE);
    assert(count == before && restart_calls == 1 && !sleeps);
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "order")) check_order();
    else if (!strcmp(argv[1], "gpio")) check_gpio();
    else if (!strcmp(argv[1], "sources")) check_sources();
    else if (!strcmp(argv[1], "changes")) check_changes();
    else if (!strcmp(argv[1], "failures")) check_failures();
    else if (!strcmp(argv[1], "final")) check_final();
    else return 2;
    return 0;
}
