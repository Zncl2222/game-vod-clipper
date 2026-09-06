"""Extraction regression tests: fake FFmpeg only, no source video is opened."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from game_vod_clipper.codex_analysis import extract_packet


class PacketExtractionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runs')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.tool = patch('game_vod_clipper.codex_analysis.resolve_tool_command', return_value=['fake-ffmpeg'])
        self.tool.start()
        self.addCleanup(self.tool.stop)

    def fake_run(self, args, **kwargs):
        target = args[-1]
        count = int(args[args.index('-frames:v') + 1])
        for i in range(count):
            path = target % (i + 1) if '%' in target else target
            Image.new('RGB', (16, 16)).save(path)
        return subprocess.CompletedProcess(args, 0, '', '')

    def test_long_sparse_packet_seeks_each_target_and_reports_progress(self):
        progress = []
        with patch('game_vod_clipper.codex_analysis.subprocess.run', side_effect=self.fake_run) as run:
            _, manifest = extract_packet(Path('unopened.mp4'), self.work, (0, 1410, 30),
                                         on_frame=lambda done, total: progress.append((done, total)))
        self.assertEqual(manifest['timestamps'], list(range(0, 1411, 30)))
        self.assertEqual(progress, [(i, 48) for i in range(1, 49)])
        for i, call in enumerate(run.call_args_list):
            args = call.args[0]
            self.assertEqual(float(args[args.index('-ss') + 1]), i * 30)
            self.assertLess(args.index('-ss'), args.index('-i'))
            self.assertLess(args.index('-threads'), args.index('-i'))
            self.assertEqual(args[args.index('-frames:v') + 1], '1')
            self.assertNotIn('-t', args)
            self.assertNotIn('fps=', ' '.join(args))
            self.assertLessEqual(call.kwargs['timeout'], 30)

    def test_short_dense_window_uses_one_pass(self):
        with patch('game_vod_clipper.codex_analysis.subprocess.run', side_effect=self.fake_run) as run:
            _, manifest = extract_packet(Path('unopened.mp4'), self.work, (10, 12, 1))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(manifest['timestamps'], [10, 11, 12])

    def test_timeout_reports_completed_frames_without_command_dump(self):
        def slow(args, **kwargs):
            if args[-1].endswith('002.jpg'):
                raise subprocess.TimeoutExpired(args, kwargs['timeout'])
            return self.fake_run(args, **kwargs)
        with patch('game_vod_clipper.codex_analysis.subprocess.run', side_effect=slow):
            with self.assertRaisesRegex(RuntimeError, '已完成 1/3 張') as error:
                extract_packet(Path('unopened.mp4'), self.work, (0, 60, 30))
        self.assertNotIn('unopened.mp4', str(error.exception))
        self.assertFalse((self.work / 'manifest.json').exists())

    def test_missing_output_cannot_reuse_stale_frames(self):
        Image.new('RGB', (16, 16)).save(self.work / 'frame-001.jpg')
        with patch('game_vod_clipper.codex_analysis.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            with self.assertRaisesRegex(ValueError, '沒有可供分析'):
                extract_packet(Path('unopened.mp4'), self.work, (0, 0, 30))

    def test_incomplete_dense_packet_is_not_sent_as_complete(self):
        def partial(args, **kwargs):
            Image.new('RGB', (16, 16)).save(self.work / 'frame-001.jpg')
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch('game_vod_clipper.codex_analysis.subprocess.run', side_effect=partial):
            with self.assertRaisesRegex(ValueError, '不完整'):
                extract_packet(Path('unopened.mp4'), self.work, (0, 2, 1))

    def test_expired_packet_budget_does_not_start_process(self):
        with patch('game_vod_clipper.codex_analysis.subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError, '逾時'):
                extract_packet(Path('unopened.mp4'), self.work, (0, 60, 30), timeout=0)
        run.assert_not_called()
