"""Host-only control checks using fake buffers; never import PYNQ or access hardware."""
import ast
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'sw/pynq/spectrum_cma_alloc_control.py'
spec=importlib.util.spec_from_file_location('cma_alloc_control_host',SOURCE)
control=importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def fake_allocator(retain=False, fail_release=False):
    state=dict(created=0,released=0,writes=0,retained=[])
    class Buffer:
        nbytes=8192
        device_address=0x100000
        virtual_address=0x200000
        base=None
        def __init__(self):
            state['created']+=1
            self.device=object();self.memory=object();self.bo=object();self.freed=False
        def __setitem__(self,key,value):
            state['writes']+=1
        def freebuffer(self):
            if fail_release:
                raise RuntimeError('HOST simulated release failure')
            state['released']+=1
            self.freed=True
            del self.bo
            if retain:
                state['retained'].append(self)
    return Buffer,state


class AllocationControlTests(unittest.TestCase):
    def fixture(self):
        path=ROOT/'build/spectrum_cma_alloc_control_20261031/fixtures'/uuid.uuid4().hex[:12]
        path.mkdir(parents=True)
        return path

    def test_balanced_control_does_not_retain_buffers(self):
        allocator,state=fake_allocator()
        result=dict(batches=[])
        phases=[]
        control.run_batches(allocator,lambda phase,address=None:phases.append(phase),result,
                            settle=lambda _:None,clock=lambda:0)
        self.assertEqual((state['created'],state['released'],state['writes']),(301,301,301))
        self.assertEqual(len(phases),8)
        self.assertEqual(result['total_allocations_including_warmup'],301)
        self.assertEqual([b['freed_markers'] for b in result['batches']],[100,100,100])
        self.assertEqual([b['bo_attributes_remaining'] for b in result['batches']],[0,0,0])
        self.assertEqual([b['buffers_alive_after_gc'] for b in result['batches']],[0,0,0])

    def test_retained_objects_are_reported(self):
        allocator,state=fake_allocator(retain=True)
        result=dict(batches=[])
        control.run_batches(allocator,lambda *args:None,result,settle=lambda _:None,clock=lambda:0)
        self.assertEqual([b['buffers_alive_after_gc'] for b in result['batches']],[101,201,301])

    def test_release_failure_stops_without_more_allocations(self):
        allocator,state=fake_allocator(fail_release=True)
        with self.assertRaisesRegex(RuntimeError,'simulated release failure'):
            control.run_batches(allocator,lambda *args:None,dict(batches=[]),settle=lambda _:None,clock=lambda:0)
        self.assertEqual(state['created'],1)

    def test_metadata_error_still_releases_allocated_buffer(self):
        buffer_type,state=fake_allocator()
        class BadMetadata(buffer_type):
            @property
            def virtual_address(self):
                raise RuntimeError('HOST metadata error')
        with self.assertRaisesRegex(RuntimeError,'metadata error'):
            control.one_allocation(BadMetadata)
        self.assertEqual((state['created'],state['released']),(1,1))

    def test_budget_stops_before_next_allocation(self):
        allocator,state=fake_allocator()
        clock=iter([0,121])
        with self.assertRaisesRegex(RuntimeError,'120second control budget'):
            control.run_batches(allocator,lambda *args:None,dict(batches=[]),settle=lambda _:None,clock=lambda:next(clock))
        self.assertEqual(state['created'],1)
        self.assertEqual(state['released'],1)

    def test_service_scan_is_not_limited_to64pids(self):
        proc=self.fixture()
        for i in range(1,90):
            folder=proc/str(i);folder.mkdir();(folder/'cmdline').write_bytes(b'other_process\0')
        folder=proc/'99999';folder.mkdir()
        (folder/'cmdline').write_bytes(b'python3\0/home/xilinx/jupyter_notebooks/spectrum_software_v1_r3/spectrum_app.py\0')
        with self.assertRaisesRegex(RuntimeError,'99999'):
            control.ensure_service_stopped(proc)
        (folder/'cmdline').write_bytes(b'other_process\0')
        control.ensure_service_stopped(proc)

    def test_source_check_is_read_only_and_rejects_changed_bytes(self):
        base=self.fixture()
        path=base/'buffer.py';path.write_bytes(b'raise RuntimeError("DO NOT EXECUTE")\n')
        expected={'buffer.py':hashlib.sha256(path.read_bytes()).hexdigest().upper()}
        spec=SimpleNamespace(submodule_search_locations=[str(base)])
        with patch.object(control,'EXPECTED_SOURCES',expected),patch.object(control.PathFinder,'find_spec',return_value=spec):
            self.assertEqual(control.check_sources()['sha256'],expected)
            path.write_bytes(b'changed source\n')
            with self.assertRaisesRegex(RuntimeError,'differs from received probe'):
                control.check_sources()
        ast.parse(SOURCE.read_text(encoding='utf-8'),feature_version=(3,6))


if __name__=='__main__':
    unittest.main()
