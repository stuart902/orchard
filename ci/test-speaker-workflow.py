#!/usr/bin/env python3
"""Bound the diagnostic build workflow; no device access or arming commands."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/j71b-speaker-window.yml'
SHA = 'aaa2a29a93afe6fea3dbe70cb246642e525b210c'


class WorkflowTests(unittest.TestCase):
    def test_exact_candidate_and_distinct_output(self):
        text = WORKFLOW.read_text()
        self.assertIn('LINUX_COMMIT: ' + SHA, text)
        self.assertIn('branches: [ci/j71b-speaker-window-nov7]', text)
        self.assertIn('name: orchard-speaker-window-components', text)
        self.assertIn('name: orchard-speaker-window-4k-checks', text)
        self.assertNotIn('--variant microphone', text)
        self.assertNotIn('gh release', text)

    def test_focused_4k_gates_full_build(self):
        text = WORKFLOW.read_text()
        self.assertIn('kernel:\n    needs: [tests, config-4k]', text)
        self.assertIn('DTC_FLAGS=-@ apple/t8010-j71b.dtb', text)
        self.assertIn('sound/soc/codecs/max98357a.o', text)
        self.assertIn('python linux/tools/testing/selftests/alsa/test_max98357a_j71b.py', text)
        self.assertIn('runs-on: ubuntu-24.04-arm', text)
        self.assertIn("ORCHARD_BUILD_NATIVE: '1'", text)

    def test_no_device_or_arming_action(self):
        text = WORKFLOW.read_text()
        self.assertNotRegex(text, r'j71b_test_arm\s*=')
        self.assertNotRegex(text, r'\b(?:ssh|scp|aplay|arecord|speaker-test|modprobe|rmmod)\s')
        self.assertNotRegex(text, r'(?:bin/orchard|\borchard)"?\s+(?:run|launch|install)\b')
        self.assertIn('--loader "$PWD/out/components/quiet/m1n1.bin"', text)
        self.assertIn('--pongo "$PWD/out/components/quiet/pongo.bin"', text)

    def test_record_preserves_exact_baselines(self):
        record = json.loads((ROOT / 'ci/j71b-audio-current.json').read_text())
        current = record['variants']['speaker']
        self.assertEqual(record['orchard_commit'], '79df400f60c76154a47fdb4dc1eff06dbb1aa8a2')
        self.assertEqual(current['base_commit'], '1b79f24831f78722e6c5fd205bc06646dd920b32')
        self.assertEqual(current['base_kernel_tree'], record['variants']['audio']['kernel_tree'])
        self.assertEqual(current['kernel_tree'], '9282aa778c0b72f7edf4f5cc474802ae14b29b98')
        self.assertEqual(current['mca_sha256'], record['variants']['audio']['mca_sha256'])
        self.assertEqual(current['dts_sha256'], record['variants']['audio']['dts_sha256'])
        self.assertEqual(len(current['diagnostic_restore']), 7)


if __name__ == '__main__':
    unittest.main(verbosity=2)
