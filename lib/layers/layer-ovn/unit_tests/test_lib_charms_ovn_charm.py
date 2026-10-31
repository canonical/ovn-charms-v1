# Copyright 2019 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
import copy
import io
import os
import textwrap
import subprocess
import tempfile
import unittest.mock as mock
import uuid

import charms_openstack.charm.core as chm_core
import charms_openstack.test_utils as test_utils

import charms.ovn_charm as ovn_charm
from charms.ovn_charm import is_deferred_event_permitted


class TestDeferredEventMixin(test_utils.PatchHelper):

    class FakeBaseClass():
        def install(self):
            return

        def configure_ovs(self, sb_conn, mlockall_changed):
            return

    class FakeCharm(ovn_charm.DeferredEventMixin, FakeBaseClass):

        @property
        def services(self):
            return ['mysvc']

    def setUp(self):
        super().setUp()
        self.charm_instance = self.FakeCharm()

    def test_deferable_services(self):
        self.assertEqual(
            sorted(self.charm_instance.deferable_services),
            sorted([
                'ovn-host',
                'openvswitch-switch',
                'mysvc',
                'ovs-vswitchd',
                'ovsdb-server',
                'ovs-record-hostname',
                'ovn-controller']))

    def test_configure_deferred_restarts(self):
        self.patch_object(
            ovn_charm.ch_core.hookenv,
            'config',
            return_value={'enable-auto-restarts': True})
        self.patch_object(
            ovn_charm.ch_core.hookenv,
            'service_name',
            return_value='myapp')
        self.patch_object(
            ovn_charm.deferred_events,
            'configure_deferred_restarts')
        self.patch_object(ovn_charm.os, 'chmod')
        self.charm_instance.configure_deferred_restarts()
        self.configure_deferred_restarts.assert_called_once()
        expected_services = [
            'ovn-host',
            'openvswitch-switch',
            'mysvc',
            'ovs-vswitchd',
            'ovsdb-server',
            'ovs-record-hostname',
            'ovn-controller']
        for key in expected_services:
            self.assertIn(key, expected_services)
        self.chmod.assert_called_once_with(
            '/var/lib/charm/myapp/policy-rc.d',
            493)

    def test_configure_deferred_restarts_unsupported(self):
        self.patch_object(ovn_charm.ch_core.hookenv, 'config', return_value={})
        self.patch_object(
            ovn_charm.deferred_events,
            'configure_deferred_restarts')
        self.charm_instance.configure_deferred_restarts()
        self.assertFalse(self.configure_deferred_restarts.called)

    def test_custom_assess_status_check(self):
        event_mock1 = mock.MagicMock()
        event_mock1.service = 'serviceA'
        event_mock1.action = 'restart'
        event_mock2 = mock.MagicMock()
        event_mock2.service = 'serviceB'
        event_mock2.action = 'restart'
        self.patch_object(
            ovn_charm.deferred_events,
            'check_restart_timestamps')
        self.patch_object(ovn_charm.deferred_events, 'get_deferred_events')
        self.patch_object(ovn_charm.deferred_events, 'get_deferred_hooks')

        # Test restart but no hook
        self.get_deferred_events.return_value = [
            event_mock1,
            event_mock2]
        self.get_deferred_hooks.return_value = []
        self.assertEqual(
            self.charm_instance.custom_assess_status_check(),
            ('active', 'Services queued for restart: serviceA, serviceB'))

        # Test hook but no restarts
        self.get_deferred_events.return_value = []
        self.get_deferred_hooks.return_value = ['configure_ovs', 'install']
        self.assertEqual(
            self.charm_instance.custom_assess_status_check(),
            (
                'active',
                ('Hooks skipped due to disabled auto restarts: configure_ovs, '
                 'install')))

        # Test restart and hook
        self.get_deferred_events.return_value = [
            event_mock1,
            event_mock2]
        self.get_deferred_hooks.return_value = ['configure_ovs', 'install']
        self.assertEqual(
            self.charm_instance.custom_assess_status_check(),
            (
                'active',
                ('Services queued for restart: serviceA, serviceB. '
                 'Hooks skipped due to disabled auto restarts: '
                 'configure_ovs, install')))

        # Test no restart and no hook
        self.get_deferred_events.return_value = []
        self.get_deferred_hooks.return_value = []
        self.assertEqual(
            self.charm_instance.custom_assess_status_check(),
            (None, None))

    def test_configure_ovs(self):
        self.patch_object(ovn_charm, 'is_deferred_event_permitted')
        self.patch_object(ovn_charm.deferred_events, 'clear_deferred_hook')

        # Test deferred events are permitted
        self.is_deferred_event_permitted.return_value = True
        self.clear_deferred_hook.reset_mock()
        self.charm_instance.configure_ovs(
            's_conn',
            'mlockall_changed',
            check_deferred_events=True)
        self.clear_deferred_hook.assert_called_once_with('configure_ovs')

        # Test deferred events are not permitted
        self.is_deferred_event_permitted.return_value = False
        self.clear_deferred_hook.reset_mock()
        self.charm_instance.configure_ovs(
            's_conn',
            'mlockall_changed',
            check_deferred_events=True)
        self.assertFalse(self.clear_deferred_hook.called)

    def test_install(self):
        self.patch_object(ovn_charm, 'is_deferred_event_permitted')
        self.patch_object(ovn_charm.deferred_events, 'clear_deferred_hook')

        # Test deferred events are permitted
        self.is_deferred_event_permitted.return_value = True
        self.clear_deferred_hook.reset_mock()
        self.charm_instance.install(check_deferred_events=True)
        self.clear_deferred_hook.assert_called_once_with('install')

        # Test deferred events are not permitted
        self.is_deferred_event_permitted.return_value = False
        self.clear_deferred_hook.reset_mock()
        self.charm_instance.install(check_deferred_events=True)
        self.assertFalse(self.clear_deferred_hook.called)

    def test_deferred_event_is_not_permitted(self):
        # Only case when deferred event is not permitted
        config_rendered = True
        enable_auto_restarts_changed = False
        check_deferred_events = True
        is_restart_permitted = False

        self.assertFalse(is_deferred_event_permitted(
            config_rendered, enable_auto_restarts_changed,
            check_deferred_events, is_restart_permitted))

    def test_deferred_event_is_permitted(self):
        # All cases when deferred event is permitted
        test_cases = [
            [True, True, True, True],
            [True, False, True, True],
            [True, True, False, True],
            [True, True, True, False],
            [True, False, False, True],
            [True, True, False, False],
            [True, False, False, False],

            [False, False, False, False],
            [False, True, False, False],
            [False, False, True, False],
            [False, False, False, True],
            [False, True, True, False],
            [False, True, False, True],
            [False, False, True, True],
            [False, True, True, True],
        ]

        for test_case in test_cases:
            self.assertTrue(is_deferred_event_permitted(
                test_case[0], test_case[1], test_case[2], test_case[3]
            ))


class TestOVNConfigurationAdapter(test_utils.PatchHelper):

    def setUp(self):
        super().setUp()
        self.charm_instance = mock.MagicMock()
        self.charm_instance.ovn_sysconfdir.return_value = '/etc/path'
        self.patch('charmhelpers.contrib.openstack.context.DPDKDeviceContext',
                   name='DPDKDeviceContext')
        self.DPDKDeviceContext.return_value = lambda: {
            'devices': {
                'fakepci': 'fakeif',
            },
            'driver': 'fakedriver',
        }
        self.patch('charmhelpers.contrib.openstack.context.SRIOVContext',
                   name='SRIOVContext')
        m = mock.patch.object(ovn_charm.ch_core.hookenv, 'config')
        m.start()
        self.target = ovn_charm.OVNConfigurationAdapter(
            charm_instance=self.charm_instance)
        m.stop()
        setattr(self, 'config', None)

    def test_ovn_key(self):
        self.assertEqual(self.target.ovn_key, '/etc/path/key_host')

    def test_ovn_cert(self):
        self.assertEqual(self.target.ovn_cert, '/etc/path/cert_host')

    def test_ovn_ca_cert(self):
        self.charm_instance.name = mock.PropertyMock().return_value = 'name'
        self.assertEqual(self.target.ovn_ca_cert, '/etc/path/name.crt')

    def test_dpdk_device(self):
        self.assertDictEqual(self.target.dpdk_device.devices,
                             {'fakepci': 'fakeif'})
        self.assertEqual(self.target.dpdk_device.driver, 'fakedriver')

    def test_bridge_interface_map_cached(self):
        # The map is read more than once in a hook, by the CPU pinning as
        # well as the bridge configuration.
        self.patch_object(ovn_charm.os_context, 'BridgePortInterfaceMap')
        bim = self.BridgePortInterfaceMap.return_value
        self.assertIs(self.target.bridge_interface_map, bim)
        self.assertIs(self.target.bridge_interface_map, bim)
        self.BridgePortInterfaceMap.assert_called_once()

    def test_sriov_device(self):
        self.assertEqual(self.target.sriov_device, self.SRIOVContext())

    def _test_mlock_d(self, config_rv, container_rv, mlock_rv):
        hookenv = ovn_charm.ch_core.hookenv
        host = ovn_charm.ch_core.host

        self.patch_object(hookenv, 'config', return_value=config_rv)
        self.patch_object(host, 'is_container', return_value=container_rv)
        self.assertEqual(self.target.mlockall_disabled, mlock_rv)

    def test_mlockall_disabled_true(self):
        self._test_mlock_d(config_rv=True, container_rv=False, mlock_rv=True)

    def test_mlockall_disabled_false(self):
        self._test_mlock_d(config_rv=False, container_rv=False, mlock_rv=False)

    def test_mlockall_disabled_none_true(self):
        self._test_mlock_d(config_rv=None, container_rv=True, mlock_rv=True)

    def test_mlockall_disabled_none_false(self):
        self._test_mlock_d(config_rv=None, container_rv=False, mlock_rv=False)

    def test__ovn_source(self):
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.patch_object(ovn_charm.ch_core.host, 'lsb_release',
                          return_value={'DISTRIB_CODENAME': 'focal'})
        # User has supplied a ovn-source config
        m = mock.patch.object(ovn_charm.ch_core.hookenv, 'config',
                              return_value={'ovn-source': 'fake-source'})
        m.start()
        self.target = ovn_charm.OVNConfigurationAdapter(
            charm_instance=self.charm_instance)
        m.stop()
        setattr(self, 'config', None)
        self.assertEqual('fake-source', self.target._ovn_source)

        # User has not supplied a ovn-source config, charm was installed at
        # this version on focal
        m = mock.patch.object(ovn_charm.ch_core.hookenv, 'config',
                              return_value={'ovn-source': ''})
        m.start()
        self.target = ovn_charm.OVNConfigurationAdapter(
            charm_instance=self.charm_instance)
        m.stop()
        setattr(self, 'config', None)
        self.assertEqual('cloud:focal-ovn-22.03', self.target._ovn_source)

        # User has not supplied a ovn-source config, charm was upgraded
        self.is_flag_set.return_value = False
        self.assertEqual('', self.target._ovn_source)

        # User has not supplied a ovn-source config, charm was installed at
        # this version on jammy
        self.is_flag_set.return_value = True
        self.lsb_release.return_value = {'DISTRIB_CODENAME': 'jammy'}
        self.assertEqual('', self.target._ovn_source)


class TestOVNConfigurationAdapterSerial(test_utils.PatchHelper):

    def setUp(self):
        super().setUp()
        self.charm_instance = mock.MagicMock()
        self.patch_object(ovn_charm.ch_core.hookenv, 'config')

        def _config_side_effect(k=None):
            opts = {
                'enable-hardware-offload': False,
                'enable-sriov': False,
                'install-doca': False,
                'enable-doca': False,
                'enable-dpdk': False,
                'vpd-device-spec':
                '[{"bus": "pci", "vendor_id": "b3ef", "device_id": "caf3"}]',
            }
            return opts[k] if k else opts

        self.config.side_effect = _config_side_effect

        self.target = ovn_charm.OVNConfigurationAdapter(
            charm_instance=self.charm_instance)

    def test_card_serial_no_serial_in_lspci(self):
        self.patch_object(ovn_charm.subprocess, 'check_output')
        self.check_output.return_value = ''
        self.assertIsNone(self.target.card_serial_number)
        self.check_output.assert_called_once_with(
            ['lspci', '-d', 'b3ef:caf3', '-vv'], text=True)

    def test_card_serial_valid_serial(self):
        self.patch_object(ovn_charm.subprocess, 'check_output')
        self.check_output.return_value = r'''
03:00.1 Ethernet controller: Ubuntu DPU Super Series
	Subsystem: Ubuntu network controller
	Control: I/O- Mem+ BusMaster+ SpecCycle- MemWINV- VGASnoop- ParErr-
	Status: Cap+ 66MHz- UDF- FastB2B- ParErr- DEVSEL=fast >TAbort- <TAbort-
	Latency: 0
	Interrupt: pin A routed to IRQ 78
	Region 0: Memory at e202000000 (64-bit, prefetchable) [size=32M]
	Expansion ROM at e000100000 [disabled] [size=1M]
	Capabilities: [48] Vital Product Data
		Product Name: Ubuntu DPU Super Series
		Read-only fields:
			[PN] Part number: jammy-jellyfish
			[EC] Engineering changes: B1
			[SN] Serial number: deadbeefcafe
			[V3] Vendor specific: 22.04
			[V0] Vendor specific: PCIeGen4 x8
			[RV] Reserved: checksum good, 1 byte(s) reserved
		End
        '''  # noqa: W191, E101  to represent the real-world lspci output.
        self.assertEqual(self.target.card_serial_number, 'deadbeefcafe')
        self.check_output.assert_called_once_with(
            ['lspci', '-d', 'b3ef:caf3', '-vv'], text=True)

    def test_card_serial_no_spec(self):
        def _config_side_effect(k=None):
            opts = {
                'enable-hardware-offload': False,
                'enable-sriov': False,
                'install-doca': False,
                'enable-doca': False,
                'enable-dpdk': False,
                'vpd-device-spec': ''
            }
            return opts[k] if k else opts

        self.config.side_effect = _config_side_effect

        self.target = ovn_charm.OVNConfigurationAdapter(
            charm_instance=self.charm_instance)

        self.assertIsNone(self.target.card_serial_number)

    def test_card_serial_invalid_spec(self):
        invalid_specs = [
            '{', '{}',
            # Not a JSON array:
            '{"bus": "pci", "vendor_id": "beef", "device_id": "cafe"}',
            # Bus isn't specified:
            '["vendor_id": "beef", "device_id": "cafe"}]',
            # Invalid device key:
            '{"bus": "pci", "vendor_id": "beef", "device": "cafe"}]',
            # Invalid device value:
            '[{"bus": "pci", "vendor_id": "beef", "device_id": 3453}]',
            # Invalid vendor key:
            '[{"bus": "pci", "vendor": "beef", "device_id": "cafe"}]',
            # Invalid vendor value:
            '[{"bus": "pci", "vendor": 6334, "device_id": "cafe"}]',
            # Missing device key:
            '[{"bus": "pci", "vendor_id": "beef"}]',
            # Missing vendor key:
            '[{"bus": "pci", "device_id": "cafe"}]',
        ]

        for invalid_spec in invalid_specs:
            def _config_side_effect(k=None):
                opts = {
                    'enable-hardware-offload': False,
                    'enable-sriov': False,
                    'install-doca': False,
                    'enable-doca': False,
                    'enable-dpdk': False,
                    'vpd-device-spec': invalid_spec
                }
                return opts[k] if k else opts

            self.config.side_effect = _config_side_effect
            self.target = ovn_charm.OVNConfigurationAdapter(
                charm_instance=self.charm_instance)
            self.assertIsNone(self.target.card_serial_number)


class TestOVNConfigurationAdapterDPDKOverlap(test_utils.PatchHelper):

    def setUp(self):
        super().setUp()
        self.charm_instance = mock.MagicMock()
        self.patch_object(ovn_charm.ch_core.hookenv, 'config')

        def _config_side_effect(k=None):
            opts = {
                'enable-hardware-offload': False,
                'enable-sriov': False,
                'install-doca': False,
                'enable-doca': False,
                'enable-dpdk': True,
            }
            return opts[k] if k else opts

        self.config.side_effect = _config_side_effect

    def test_ovs_dpdk_cpu_overlap_not_from_config(self):
        self.patch_object(ovn_charm.os_context, 'DPDKDeviceContext')
        self.DPDKDeviceContext().return_value = {}
        dpdk_context = mock.MagicMock()
        self.patch_object(ovn_charm.os_context, 'OVSDPDKDeviceContext',
                          return_value=dpdk_context)
        # 000000000000000001000010
        dpdk_context.cpu_mask.return_value = '0x42'
        # 101011110000000010011101
        dpdk_context.pmd_cpu_mask.return_value = '0xaf009d'
        # 101011110000000011011111
        dpdk_context.pmd_cpu_mask.return_value = '0xaf00df'
        # pmd-cpu-set is not what the PMD threads necessarily end up on, so
        # the overlap is checked against what Open vSwitch was given.
        self.target = ovn_charm.OVNConfigurationAdapter(
            charm_instance=self.charm_instance)
        self.assertEqual(self.target.validation_errors, {})


class TestIfdataForDatapath(test_utils.PatchHelper):

    def test_passthrough(self):
        # BridgePortInterfaceMap already resolves the interface types of
        # upstream Open vSwitch.
        ifdata = {'type': 'dpdk', 'options': {'dpdk-devargs': '0000:42:01.0'}}
        for datapath_type in ('system', 'netdev'):
            self.assertEqual(
                ovn_charm.ifdata_for_datapath(ifdata, datapath_type), ifdata)

    def test_doca(self):
        self.assertEqual(
            ovn_charm.ifdata_for_datapath({'mtu-request': 9000}, 'doca'),
            {
                'mtu-request': 9000,
                'type': 'doca',
                'options': {'dpdk-lsc-interrupt': 'true'},
            })

    def test_doca_retains_options(self):
        self.assertEqual(
            ovn_charm.ifdata_for_datapath(
                {'options': {'keep': 'this'}}, 'doca'),
            {
                'type': 'doca',
                'options': {'keep': 'this', 'dpdk-lsc-interrupt': 'true'},
            })


class Helper(test_utils.PatchHelper):

    def setUp(self, release=None, is_flag_set_return_value=False, config=None):
        super().setUp()
        self.patch_release(release or 'ussuri')
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=is_flag_set_return_value)
        self.patch_object(
            ovn_charm.charms_openstack.adapters, '_custom_config_properties')
        self._custom_config_properties.side_effect = {}
        self.patch('charmhelpers.contrib.openstack.context.DPDKDeviceContext',
                   name='DPDKDeviceContext')
        self.DPDKDeviceContext.return_value = lambda: {
            'devices': {
                'fakepci': 'fakeif',
            },
            'driver': 'fakedriver',
        }
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.sysfs = tmpdir.name
        self.cpu_affinity_drop_in = os.path.join(
            tmpdir.name, 'ovs-vswitchd.service.d', 'charm-cpu-affinity.conf')
        self.patch_object(ovn_charm, 'OVS_VSWITCHD_CPU_AFFINITY_DROP_IN',
                          new=self.cpu_affinity_drop_in)
        self.patch_object(ovn_charm.epa_client, 'is_available',
                          name='epa_available', return_value=False)
        # Never look at the sysfs of the machine running the tests.
        for attr, path in (('SYSFS_NET', 'net'),
                           ('SYSFS_PCI', 'pci'),
                           ('SYSFS_NUMA', 'node'),
                           ('SYSFS_CPU', 'cpu')):
            self.patch_object(ovn_charm, attr,
                              new=os.path.join(self.sysfs, path))
        self.patch_object(ovn_charm.ch_core.hookenv, 'config')

        def _fake_config(x=None):
            cfg = config or {
                'enable-hardware-offload': False,
                'enable-sriov': False,
                'install-doca': False,
                'enable-doca': False,
                'enable-dpdk': False,
                'bridge-interface-mappings': 'br-ex:eth0',
                'prefer-chassis-as-gw': False,
                'ovn-monitor-all': False,
                'vpd-device-spec':
                '[{"bus": "pci", "vendor_id": "beef", "device_id": "cafe"}]',
            }
            if x:
                return cfg.get(x)
            return cfg

        self.config.side_effect = _fake_config
        self.enable_openstack = mock.PropertyMock
        self.enable_openstack.return_value = False
        self.target = ovn_charm.BaseOVNChassisCharm()
        self.patch(
            'charms.ovn_charm.BaseOVNChassisCharm.enable_openstack',
            new_callable=self.enable_openstack)
        # remove the 'is_flag_set' patch so the tests can use it
        self._patches['is_flag_set'].stop()
        setattr(self, 'is_flag_set', None)
        del self._patches['is_flag_set']
        del self._patches_start['is_flag_set']

        self.patch('charmhelpers.contrib.openstack.context.DPDKDeviceContext',
                   name='DPDKDeviceContext')
        self.DPDKDeviceContext.return_value = lambda: {
            'devices': {
                'fakepci': 'fakeif',
            },
            'driver': 'fakedriver',
        }

    def tearDown(self):
        super().tearDown()
        chm_core._release_selector_function = None
        chm_core._package_type_selector_function = None
        chm_core._releases = None
        chm_core._singleton = None

    def patch_target(self, attr, return_value=None):
        mocked = mock.patch.object(self.target, attr)
        self._patches[attr] = mocked
        started = mocked.start()
        started.return_value = return_value
        self._patches_start[attr] = started
        setattr(self, attr, started)

    def patch_sysfs(self, numa_nodes=2, memory_only=()):
        """Point the charm at a fake sysfs with ``numa_nodes`` NUMA nodes.

        :param numa_nodes: Number of NUMA nodes, with 64 CPUs each.
        :type numa_nodes: int
        :param memory_only: NUMA nodes without CPUs, out of those.
        :type memory_only: Iterable[int]
        """
        for path in ('net', 'pci', 'node', 'cpu'):
            os.makedirs(os.path.join(self.sysfs, path))
        for node in range(numa_nodes):
            node_dir = os.path.join(self.sysfs, 'node', f'node{node}')
            os.makedirs(node_dir)
            with open(os.path.join(node_dir, 'cpulist'), 'w') as f:
                if node not in memory_only:
                    f.write(f'{node * 64}-{node * 64 + 63}')
                f.write('\n')
        # Not a NUMA node.
        os.makedirs(os.path.join(self.sysfs, 'node', 'power'))

    def add_netdev(self, name, numa_node=None, lower=()):
        """Add a network device to the fake sysfs.

        :param name: Name of the device.
        :type name: str
        :param numa_node: NUMA node of the PCI device behind it, if any.
        :type numa_node: Optional[int]
        :param lower: Devices it is stacked on, for example bond members.
        :type lower: Iterable[str]
        """
        netdev = os.path.join(self.sysfs, 'net', name)
        os.makedirs(netdev)
        if numa_node is not None:
            os.makedirs(os.path.join(netdev, 'device'))
            with open(os.path.join(netdev, 'device', 'numa_node'), 'w') as f:
                f.write(f'{numa_node}\n')
        for member in lower:
            os.symlink(os.path.join(self.sysfs, 'net', member),
                       os.path.join(netdev, f'lower_{member}'))

    def patch_datapath_types(self, datapath_types):
        """Present ``datapath_types`` as offered by ovs-vswitchd.

        :param datapath_types: Datapath types to present.
        :type datapath_types: any
        :returns: The mocked ``open_vswitch`` table object.
        :rtype: mock.MagicMock
        """
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [
            {'datapath_types': datapath_types}]
        self.SimpleOVSDB.return_value = ovsdb
        return ovsdb


class TestOVNChassisCharmWithOpenStack(Helper):

    def setUp(self):
        super().setUp()
        self.enable_openstack.return_value = True

    def test_optional_openstack_metadata(self):
        self.assertEqual(self.target.packages, [
            'ovn-host', 'neutron-ovn-metadata-agent',
        ])
        self.assertEqual(self.target.services, [
            'ovn-host', 'neutron-ovn-metadata-agent'])
        self.assertDictEqual(self.target.restart_map, {
            '/etc/default/openvswitch-switch': [],
            '/etc/netplan/150-charm-ovn.yaml': [],
            '/etc/neutron/neutron_ovn_metadata_agent.ini': [
                'neutron-ovn-metadata-agent'],
            '/etc/openvswitch/system-id.conf': [],
        })
        self.assertEqual(self.target.nrpe_check_services, [
            'ovn-controller', 'ovs-vswitchd', 'ovsdb-server',
            'neutron-ovn-metadata-agent'])


class TestDPDKOVNChassisCharmExtraLibs(Helper):

    def setUp(self):
        self.local_config = {
            'enable-hardware-offload': False,
            'enable-sriov': False,
            'install-doca': False,
            'enable-doca': False,
            'enable-dpdk': True,
            'dpdk-bond-mappings': ('dpdk-bond0:a0:36:9f:dd:37:a4 '
                                   'dpdk-bond0:a0:36:9f:dd:3e:9c'),
            'bridge-interface-mappings': 'br-ex:eth0 br-data:dpdk-bond0',
            'ovn-bridge-mappings': (
                'provider:br-ex other:br-data'),
            'prefer-chassis-as-gw': False,
            'ovn-monitor-all': False,
            'dpdk-runtime-libraries': '',
            'vpd-device-spec': '',
            'ovn-source': 'distro',
        }
        super().setUp(config=self.local_config)

        self.run = mock.Mock()
        self.patch('charms.ovn_charm.BaseOVNChassisCharm.run',
                   new_callable=self.run)
        self.run.start()
        self.called_process = self.run.return_value
        self.called_process.returncode = 0

    def test_single_match(self):
        apt_cache_output = textwrap.dedent(
        """
        librte-net-hinic21:
          Installed: 20.11.3-0ubuntu0.21.04.2
          Candidate: 20.11.3-0ubuntu0.21.04.2
          Version table:
         *** 20.11.3-0ubuntu0.21.04.2 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute-updates/universe amd64 Packages
                100 /var/lib/dpkg/status
             20.11.1-1 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute/universe amd64 Packages
        """  # noqa
        )
        self.called_process.stdout = apt_cache_output

        self.local_config['dpdk-runtime-libraries'] = 'hinic'
        target = ovn_charm.BaseOVNChassisCharm()
        self.assertEqual(target.additional_dpdk_libraries, [
            'librte-net-hinic21'])
        self.assertEqual(target.packages, [
            'ovn-host', 'openvswitch-switch-dpdk', 'librte-net-hinic21'])

    def test_multiple_matches(self):
        apt_cache_output = textwrap.dedent(
        """
        librte-net-mlx5-21:
          Installed: 20.11.3-0ubuntu0.21.04.2
          Candidate: 20.11.3-0ubuntu0.21.04.2
          Version table:
         *** 20.11.3-0ubuntu0.21.04.2 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute-updates/main amd64 Packages
                100 /var/lib/dpkg/status
             20.11.1-1 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute/main amd64 Packages
        librte-regex-mlx5-21:
          Installed: 20.11.3-0ubuntu0.21.04.2
          Candidate: 20.11.3-0ubuntu0.21.04.2
          Version table:
         *** 20.11.3-0ubuntu0.21.04.2 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute-updates/universe amd64 Packages
                100 /var/lib/dpkg/status
             20.11.1-1 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute/universe amd64 Packages
        librte-common-mlx5-21:
          Installed: 20.11.3-0ubuntu0.21.04.2
          Candidate: 20.11.3-0ubuntu0.21.04.2
          Version table:
         *** 20.11.3-0ubuntu0.21.04.2 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute-updates/main amd64 Packages
                100 /var/lib/dpkg/status
             20.11.1-1 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute/main amd64 Packages
        librte-vdpa-mlx5-21:
          Installed: 20.11.3-0ubuntu0.21.04.2
          Candidate: 20.11.3-0ubuntu0.21.04.2
          Version table:
         *** 20.11.3-0ubuntu0.21.04.2 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute-updates/universe amd64 Packages
                100 /var/lib/dpkg/status
             20.11.1-1 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute/universe amd64 Packages
        """  # noqa
        )
        self.called_process.stdout = apt_cache_output

        self.local_config['dpdk-runtime-libraries'] = 'mlx5'
        target = ovn_charm.BaseOVNChassisCharm()
        self.assertEqual(target.additional_dpdk_libraries, [
            'librte-net-mlx5-21', 'librte-regex-mlx5-21',
            'librte-common-mlx5-21', 'librte-vdpa-mlx5-21'])

    def test_specific_package(self):
        self.local_config['dpdk-runtime-libraries'] = 'librte-net-mlx5-21'
        target = ovn_charm.BaseOVNChassisCharm()
        self.assertEqual(target.additional_dpdk_libraries, [
            'librte-net-mlx5-21'])
        self.run.assert_not_called()

    def test_none_package(self):
        self.local_config['dpdk-runtime-libraries'] = 'None'
        target = ovn_charm.BaseOVNChassisCharm()
        self.assertEqual(target.additional_dpdk_libraries, [])
        self.run.assert_not_called()

    def test_multiple_packages(self):
        process1 = mock.Mock()
        process1.stdout = textwrap.dedent(
        """
        librte-net-hinic21:
          Installed: 20.11.3-0ubuntu0.21.04.2
          Candidate: 20.11.3-0ubuntu0.21.04.2
          Version table:
         *** 20.11.3-0ubuntu0.21.04.2 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute-updates/universe amd64 Packages
                100 /var/lib/dpkg/status
             20.11.1-1 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute/universe amd64 Packages
        """  # noqa
        )
        process2 = mock.Mock()
        process2.stdout = textwrap.dedent(
        """
        librte-net-mlx5-21:
          Installed: 20.11.3-0ubuntu0.21.04.2
          Candidate: 20.11.3-0ubuntu0.21.04.2
          Version table:
         *** 20.11.3-0ubuntu0.21.04.2 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute-updates/main amd64 Packages
                100 /var/lib/dpkg/status
             20.11.1-1 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute/main amd64 Packages
        librte-regex-mlx5-21:
          Installed: 20.11.3-0ubuntu0.21.04.2
          Candidate: 20.11.3-0ubuntu0.21.04.2
          Version table:
         *** 20.11.3-0ubuntu0.21.04.2 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute-updates/universe amd64 Packages
                100 /var/lib/dpkg/status
             20.11.1-1 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute/universe amd64 Packages
        librte-common-mlx5-21:
          Installed: 20.11.3-0ubuntu0.21.04.2
          Candidate: 20.11.3-0ubuntu0.21.04.2
          Version table:
         *** 20.11.3-0ubuntu0.21.04.2 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute-updates/main amd64 Packages
                100 /var/lib/dpkg/status
             20.11.1-1 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute/main amd64 Packages
        librte-vdpa-mlx5-21:
          Installed: 20.11.3-0ubuntu0.21.04.2
          Candidate: 20.11.3-0ubuntu0.21.04.2
          Version table:
         *** 20.11.3-0ubuntu0.21.04.2 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute-updates/universe amd64 Packages
                100 /var/lib/dpkg/status
             20.11.1-1 500
                500 http://us.archive.ubuntu.com/ubuntu hirsute/universe amd64 Packages
        """  # noqa
        )

        self.run.side_effect = [process1, process2]

        self.local_config['dpdk-runtime-libraries'] = 'hinic mlx'
        target = ovn_charm.BaseOVNChassisCharm()
        self.assertEqual(target.additional_dpdk_libraries, [
            'librte-net-hinic21', 'librte-net-mlx5-21', 'librte-regex-mlx5-21',
            'librte-common-mlx5-21', 'librte-vdpa-mlx5-21'])

    def test_package_not_found(self):
        # Missing packages don't have output via this command
        self.called_process.stdout = ''
        self.local_config['dpdk-runtime-libraries'] = 'missing'
        target = ovn_charm.BaseOVNChassisCharm()
        self.assertEqual(target.additional_dpdk_libraries, ['missing'])


class TestDPDKOVNChassisCharm(Helper):

    def setUp(self):
        super().setUp(config={
            'enable-hardware-offload': False,
            'enable-sriov': False,
            'install-doca': False,
            'enable-doca': False,
            'enable-dpdk': True,
            'dpdk-bond-mappings': ('dpdk-bond0:a0:36:9f:dd:37:a4 '
                                   'dpdk-bond0:a0:36:9f:dd:3e:9c'),
            'bridge-interface-mappings': 'br-ex:eth0 br-data:dpdk-bond0',
            'ovn-bridge-mappings': (
                'provider:br-ex other:br-data'),
            'prefer-chassis-as-gw': False,
            'ovn-monitor-all': False,
            'dpdk-runtime-libraries': '',
            'vpd-device-spec': '',
            'pmd-cpu-set': '',
            'ovn-source': 'distro',
            'ovs-cpu-cores': 0,
            'pmd-cpu-cores': 4,
        })

    def test_datapath_type(self):
        self.assertEqual(self.target.datapath_type, 'netdev')

    def test__init__(self):
        self.assertEqual(self.target.packages, [
            'ovn-host', 'openvswitch-switch-dpdk'])
        self.assertDictEqual(self.target.restart_map, {
            '/etc/default/openvswitch-switch': [],
            '/etc/dpdk/interfaces': ['dpdk'],
            '/etc/netplan/150-charm-ovn.yaml': [],
            '/etc/openvswitch/system-id.conf': [],
        })

    def test_configure_bridges(self):
        self.patch_object(ovn_charm.os_context, 'BridgePortInterfaceMap')
        dict_bpi = {
            'br-ex': {     # bridge
                'eth0': {  # port
                           # interface(s) with data
                    'eth0': {'data': 'fake'},
                },
            },
            'br-data': {
                'dpdk-xxx': {
                    'if0': {'fake': 'data'},
                    'if1': {'fake': 'data'}
                },
            },
            'br-int': {
                'someport': {
                    'someport': {'data': 'fake'},
                },
            },
        }
        mock_bpi = mock.MagicMock()
        mock_bpi.items.return_value = dict_bpi.items()
        mock_bpi.__iter__.side_effect = lambda: iter(dict_bpi)
        mock_bpi.__contains__.side_effect = dict_bpi.__contains__
        mock_bpi.__getitem__.side_effect = lambda x: dict_bpi.__getitem__(x)
        mock_bpi.get_ifdatamap.side_effect = lambda x, y: {
            k: v for k, v in dict_bpi[x][y].items()}
        self.BridgePortInterfaceMap.return_value = mock_bpi
        self.patch_object(ovn_charm.os_context, 'BondConfig')
        mock_bondconfig = mock.MagicMock()
        mock_bondconfig.get_ovs_portdata.return_value = 'fakebondconfig'
        self.BondConfig.return_value = mock_bondconfig
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')

        ovsdb = mock.MagicMock()
        ovsdb.bridge.find.side_effect = [
            [
                {'name': 'delete-bridge'},
                {'name': 'br-int'},
            ],
            StopIteration,
        ]
        ovsdb.port.find.return_value = [{'name': 'delete-port'}]
        self.SimpleOVSDB.return_value = ovsdb

        self.patch_object(ovn_charm.ch_ovs, 'del_bridge')
        self.patch_object(ovn_charm.ch_ovs, 'del_bridge_port')
        self.patch_object(ovn_charm.ch_ovs, 'add_bridge')
        self.patch_object(ovn_charm.ch_ovs, 'get_bridge_ports')
        self.get_bridge_ports().__iter__.return_value = []
        self.patch_object(ovn_charm.ch_ovs, 'add_bridge_bond')
        self.patch_object(ovn_charm.ch_ovs, 'add_bridge_port')
        self.patch_target('check_if_paused')
        self.check_if_paused.return_value = ('some', 'reason')
        self.patch_target('_get_port_type')
        self._get_port_type.return_value = 'dpdk'
        self.target.configure_bridges()
        self.BridgePortInterfaceMap.assert_not_called()
        self.check_if_paused.return_value = (None, None)
        self.target.configure_bridges()
        self.BridgePortInterfaceMap.assert_called_once_with(
            bridges_key='bridge-interface-mappings')
        # br-int should not be deleted when not in config, even when managed
        self.del_bridge.assert_called_once_with('delete-bridge')
        # since we manage it we will delete non-existant managed ports in it
        self.del_bridge_port.assert_has_calls([
            mock.call('br-int', 'delete-port', linkdown=False),
        ])
        # br-int will always be added/updated regardless of presence in config
        self.add_bridge.assert_has_calls([
            mock.call(
                'br-int',
                brdata={
                    'external-ids': {'charm-ovn-chassis': 'managed'},
                    'datapath-type': 'netdev',
                    'protocols': 'OpenFlow13,OpenFlow15',
                    'fail-mode': 'secure',
                    'other-config': {'disable-in-band': 'true'},
                }),
            mock.call(
                'br-data',
                brdata={
                    'external-ids': {'charm-ovn-chassis': 'managed'},
                    'datapath-type': 'netdev',
                    'protocols': 'OpenFlow13,OpenFlow15',
                    'fail-mode': 'standalone',
                }),
            mock.call(
                'br-ex',
                brdata={
                    'external-ids': {'charm-ovn-chassis': 'managed'},
                    'datapath-type': 'netdev',
                    'protocols': 'OpenFlow13,OpenFlow15',
                    'fail-mode': 'standalone',
                }),
        ], any_order=True)
        self.add_bridge_bond.assert_called_once_with(
            'br-data', 'dpdk-xxx', ['if0', 'if1'], 'fakebondconfig', {
                'if0': {
                    'fake': 'data',
                    'external-ids': {'charm-ovn-chassis': 'br-data'}},
                'if1': {
                    'fake': 'data',
                    'external-ids': {'charm-ovn-chassis': 'br-data'}},
            })
        self.add_bridge_port.assert_called_once_with(
            'br-ex', 'eth0', ifdata={
                'data': 'fake',
                'external-ids': {'charm-ovn-chassis': 'br-ex'}},
            linkup=False, promisc=None, portdata={
                'external-ids': {'charm-ovn-chassis': 'br-ex'}}),
        ovsdb.open_vswitch.set.assert_called_once_with(
            '.', 'external_ids:ovn-bridge-mappings',
            'other:br-data,provider:br-ex')
        ovsdb.open_vswitch.remove.assert_called_once_with(
            '.', 'external_ids', 'ovn-cms-options')

    def test_dpdk_eal_allow_devices(self):
        self.patch_object(ovn_charm.ch_core.host, 'cmp_pkgrevno')
        single_device = {'0000:42:01.0': ('eth0', '00:53:00:00:42:01')}
        devices = copy.copy(single_device)
        devices.update({'0000:42:02.0': ('eth1', '00:53:00:00:42:02')})

        # DPDK 20.11.3 or newer
        self.cmp_pkgrevno.return_value = 0
        self.assertEqual(
            self.target.dpdk_eal_allow_devices(single_device),
            '-a 0000:42:01.0')
        self.assertEqual(
            self.target.dpdk_eal_allow_devices(devices),
            '-a 0000:42:01.0 -a 0000:42:02.0')

        # Older DPDK releases
        self.cmp_pkgrevno.return_value = -1
        self.assertEqual(
            self.target.dpdk_eal_allow_devices(single_device),
            '-w 0000:42:01.0')
        self.assertEqual(
            self.target.dpdk_eal_allow_devices(devices),
            '-w 0000:42:01.0 -w 0000:42:02.0')

    def patch_applied_masks(self, other_config):
        self.patch_object(ovn_charm.ch_core.host, 'service_running',
                          return_value=True)
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'datapath_types': ['system', 'netdev'],
            'other_config': other_config,
        }]
        self.SimpleOVSDB.return_value = ovsdb

    def test_custom_assess_status_last_check_overlap(self):
        self.patch_applied_masks({'dpdk-lcore-mask': '0x1',
                                  'pmd-cpu-mask': '0xf'})
        self.assertEqual(
            self.target.custom_assess_status_last_check(),
            ('blocked',
             'Fix overlap between dpdk-lcore-mask and pmd-cpu-mask.'))

    def test_custom_assess_status_last_check_no_overlap(self):
        self.patch_applied_masks({'dpdk-lcore-mask': '0x1',
                                  'pmd-cpu-mask': '0x1e'})
        self.assertEqual(self.target.custom_assess_status_last_check(),
                         (None, None))

    def test_configure_ovs_dpdk_pinned(self):
        # Open vSwitch only restores the affinity of its main thread after
        # DPDK has moved it to the main lcore when it picked the lcore
        # itself, so an explicit dpdk-lcore-mask would take ovs-vswitchd
        # off the CPUs it is pinned to.
        dpdk_context = mock.MagicMock()
        self.patch_object(ovn_charm.os_context, 'OVSDPDKDeviceContext',
                          return_value=dpdk_context)
        dpdk_context.cpu_mask.return_value = '0x1'
        self.patch_target('dpdk_eal_allow_devices')
        self.patch_target('pmd_cpu_mask', return_value=None)
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {'dpdk-lcore-mask': '0x1'}}]
        self.SimpleOVSDB.return_value = ovsdb
        os.makedirs(os.path.dirname(self.cpu_affinity_drop_in))
        with open(self.cpu_affinity_drop_in, 'w') as f:
            f.write('[Service]\nCPUAffinity=8-23\n')
        self.assertTrue(self.target.configure_ovs_dpdk())
        ovsdb.open_vswitch.remove.assert_called_once_with(
            '.', 'other_config', 'dpdk-lcore-mask')

    def test_configure_ovs_dpdk(self):
        dpdk_context = mock.MagicMock()
        self.patch_object(ovn_charm.os_context, 'OVSDPDKDeviceContext',
                          return_value=dpdk_context)
        self.patch_target('dpdk_eal_allow_devices')
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        opvs = mock.MagicMock()
        self.SimpleOVSDB.return_value = opvs

        # No existing config, confirm restart and values set as expected
        opvs.open_vswitch.__iter__.return_value = [
            {'other_config': {}}]
        dpdk_context.cpu_mask.return_value = '0x42'
        dpdk_context.socket_memory.return_value = '1024,1024'
        self.dpdk_eal_allow_devices.return_value = '-a 0000:42:01.0'
        self.target.options.pmd_cpu_set = '0-7,^1,^5,^6,16-23,^20,^22'
        dpdk_context.pmd_cpu_mask.return_value = '0xaf009d'
        self.assertTrue(self.target.configure_ovs_dpdk())
        opvs.open_vswitch.set.assert_has_calls([
            mock.call('.', 'other_config:dpdk-lcore-mask', '0x42'),
            mock.call('.', 'other_config:dpdk-socket-mem', '1024,1024'),
            mock.call('.', 'other_config:dpdk-init', 'true'),
            mock.call('.', 'other_config:dpdk-extra', '-a 0000:42:01.0'),
            mock.call('.', 'other_config:pmd-cpu-mask', '0xaf009d'),
        ])

        # Existing config, confirm no restart nor values set
        opvs.open_vswitch.__iter__.return_value = [
            {'other_config': {
                'dpdk-lcore-mask': '0x42',
                'dpdk-socket-mem': '1024,1024',
                'dpdk-init': 'true',
                'dpdk-extra': '-a 0000:42:01.0',
                'pmd-cpu-mask': '0xaf009d',
            }}]
        opvs.open_vswitch.reset_mock()
        self.assertFalse(self.target.configure_ovs_dpdk())

        # Existing config, confirm restart and values updated as expected
        opvs.open_vswitch.__iter__.return_value = [
            {'other_config': {
                'dpdk-lcore-mask': '0x51',
                'dpdk-socket-mem': '1024,1024',
                'dpdk-init': 'true',
                'dpdk-extra': '-a 0000:42:01.0',
                'pmd-cpu-mask': '0xaf009d',
            }}]
        self.assertTrue(self.target.configure_ovs_dpdk())
        opvs.open_vswitch.set.assert_called_once_with(
            '.', 'other_config:dpdk-lcore-mask', '0x42')

        # Existing config, confirm reset of pmd-cpu-set config option results
        # in removal of the pmd-cpu-mask paramter in order to use OVS defaults
        opvs.open_vswitch.__iter__.return_value = [
            {'other_config': {
                'dpdk-lcore-mask': '0x42',
                'dpdk-socket-mem': '1024,1024',
                'dpdk-init': 'true',
                'dpdk-extra': '-a 0000:42:01.0',
                'pmd-cpu-mask': '0xaf009d',
            }}]
        self.target.options.pmd_cpu_set = None
        self.assertTrue(self.target.configure_ovs_dpdk())
        opvs.open_vswitch.remove.assert_called_once_with(
            '.', 'other_config', 'pmd-cpu-mask')

        self.assertEqual(self.target.custom_assess_status_last_check(),
                         (None, None))

    def test_purge_packages(self):
        # The DOCA packages are purged when they are ours and no longer
        # wanted.
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.assertEqual(
            self.target.purge_packages,
            [
                'mlnx-switchdev-mode',
                'sriov-netplan-shim',
                'doca-networking',
                'mlnx-fw-updater',
            ])

    def test_install(self):
        self.patch_target('configure_source')
        self.patch_target('run')
        self.patch_target('update_api_ports')
        self.patch_target('render_configs')
        self.patch_target('remove_obsolete_packages')
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        self.patch_object(ovn_charm.reactive, 'is_flag_set', return_value=True)
        self.patch_object(ovn_charm.os.path, 'exists', return_value=False)
        self.enable_openstack.return_value = False
        self.target.install()
        self.run.assert_called_once_with(
            'update-alternatives', '--set', 'ovs-vswitchd',
            '/usr/lib/openvswitch-switch-dpdk/ovs-vswitchd-dpdk')

        # Confirm that vhost-user directory is setup when OpenStack enabled
        self.run.reset_mock()
        self.enable_openstack.return_value = True
        self.target.install()
        self.run.assert_has_calls([
            mock.call('update-alternatives', '--set', 'ovs-vswitchd',
                      '/usr/lib/openvswitch-switch-dpdk/ovs-vswitchd-dpdk'),
            mock.call('systemd-tmpfiles', '--create'),
        ])

    def test__should_linkdown(self):
        # enable-dpdk = True
        self.patch_target('_get_port_type')
        # Normal port with interfaces that should be bound to kernel driver
        self._get_port_type.return_value = ''
        self.assertFalse(self.target._should_linkdown('fake-port'))
        # DPDK port with interfaces that should not be bound to kernel driver
        self._get_port_type.return_value = 'dpdk'
        self.assertFalse(self.target._should_linkdown('fake-port'))


class TestOVNChassisCharmOvnSourceFocal(Helper):

    def setUp(self):
        super().setUp(config={'enable_dpdk': False,
                              'install-doca': False,
                              'enable-doca': False,
                              'ovn-source': ''})

    def test_configure_sources(self):
        self.target.source_config_key = ''
        self.patch_target('configure_ovn_source')
        self.patch_target('configure_source')
        self.target.configure_sources()
        self.configure_ovn_source.assert_called_once_with()
        self.assertFalse(self.configure_source.called)

    def test_configure_ovn_source(self):
        self.patch_object(ovn_charm.OVNConfigurationAdapter,
                          '_ovn_source',
                          new=mock.PropertyMock())
        self._ovn_source.return_value = 'cloud:focal-ovn-22.03'
        self.patch_object(ovn_charm.ch_fetch, 'add_source')
        self.patch_object(ovn_charm.ch_fetch, 'apt_update')
        self.target.configure_ovn_source()
        self.add_source.assert_called_once_with('cloud:focal-ovn-22.03')

        self.add_source.reset_mock()
        self._ovn_source.return_value = ''
        self.target.configure_ovn_source()
        self.assertFalse(self.add_source.called)


class TestOVNDedicatedChassisCharmSourceOption(Helper):

    def setUp(self):
        super().setUp(config={'enable_dpdk': False,
                              'install-doca': False,
                              'enable-doca': False,
                              'source': 'cloud:focal-yoga',
                              'ovn-source': ''})

    def test_configure_sources(self):
        self.target.source_config_key = 'source'
        self.patch_target('configure_ovn_source')
        self.patch_target('configure_source')
        self.target.configure_sources()
        self.configure_ovn_source.assert_called_once_with()
        self.configure_source.assert_called_once_with()


class TestOVNChassisCharm(Helper):

    def setUp(self):
        self.local_config = {
            'enable-hardware-offload': False,
            'enable-sriov': False,
            'install-doca': False,
            'enable-doca': False,
            'enable-dpdk': False,
            'bridge-interface-mappings': (
                'br-provider:00:01:02:03:04:05 br-other:eth5'),
            'ovn-bridge-mappings': (
                'provider:br-provider other:br-other'),
            'prefer-chassis-as-gw': True,
            'ovn-monitor-all': True,
            'vpd-device-spec':
            '[{"bus": "pci", "vendor_id": "beef", "device_id": "cafe"}]',
            'ovn-source': 'distro',
            'ovs-exporter-channel': '',
            'enable-version-pinning': False,
            'pmd-cpu-set': None,
            'ovs-cpu-cores': 0,
            'pmd-cpu-cores': 4,
        }
        super().setUp(config=self.local_config)

    def test_optional_openstack_metadata(self):
        self.assertEqual(self.target.packages, ['ovn-host'])
        self.assertEqual(self.target.services, ['ovn-host'])

    def test_datapath_type(self):
        self.patch_datapath_types(['system', 'netdev'])
        self.assertEqual(self.target.datapath_type, 'system')

    def test_datapath_type_provisioned_by_image(self):
        # LP: #2170179.  A host may arrive with OVS-DOCA installed and
        # configured by its image, and moving it onto the kernel datapath
        # its Open vSwitch is no longer configured for breaks it.
        self.patch_datapath_types(['system', 'doca'])
        self.assertEqual(self.target.datapath_type, 'doca')

    def test_pmd_cpu_mask_system_datapath(self):
        # The kernel datapath has no PMD threads to pin.
        self.patch_datapath_types(['system', 'netdev'])
        self.target.options.pmd_cpu_set = '8-11'
        self.assertIsNone(self.target.pmd_cpu_mask())

    def patch_bridge_interface_map(self, ifdatamap):
        """Map one port with interfaces ``ifdatamap`` on ``br-data``."""
        bim = mock.MagicMock()
        bim.__iter__.return_value = iter(['br-data'])
        bim.__getitem__.side_effect = lambda br: ['port0']
        bim.get_ifdatamap.return_value = ifdatamap
        self.patch_object(ovn_charm.OVNConfigurationAdapter,
                          'bridge_interface_map', new=bim)

    def test_interface_numa_nodes(self):
        self.patch_sysfs()
        self.add_netdev('eth0', numa_node=1)
        self.assertEqual(ovn_charm.interface_numa_nodes('eth0', {}), {1})

    def test_interface_numa_nodes_bond(self):
        # A bond has no device of its own, its members do.
        self.patch_sysfs()
        self.add_netdev('eth0', numa_node=0)
        self.add_netdev('eth1', numa_node=1)
        self.add_netdev('bond0', lower=('eth0', 'eth1'))
        self.assertEqual(ovn_charm.interface_numa_nodes('bond0', {}), {0, 1})

    def test_interface_numa_nodes_without_numa(self):
        # The kernel reports -1 for a device not attached to a NUMA node.
        self.patch_sysfs()
        self.add_netdev('eth0', numa_node=-1)
        self.add_netdev('veth0')
        self.assertEqual(ovn_charm.interface_numa_nodes('eth0', {}), set())
        self.assertEqual(ovn_charm.interface_numa_nodes('veth0', {}), set())
        self.assertEqual(ovn_charm.interface_numa_nodes('missing', {}), set())

    def test_interface_numa_nodes_dpdk(self):
        # A port bound to a DPDK driver has no network device left.
        self.patch_sysfs()
        pci = os.path.join(self.sysfs, 'pci', '0000:42:01.0')
        os.makedirs(pci)
        with open(os.path.join(pci, 'numa_node'), 'w') as f:
            f.write('1\n')
        self.assertEqual(
            ovn_charm.interface_numa_nodes(
                'dpdk-a1b2c3d', {'options': {'dpdk-devargs': '0000:42:01.0'}}),
            {1})

    def test_host_numa_nodes(self):
        self.patch_sysfs(numa_nodes=2)
        self.assertEqual(ovn_charm.host_numa_nodes(), [0, 1])

    def test_host_numa_nodes_memory_only(self):
        # The EPA orchestrator does not know of NUMA nodes without CPUs,
        # such as those of CXL memory expanders, and refuses any request
        # for them, releases included.
        self.patch_sysfs(numa_nodes=3, memory_only=(2,))
        self.assertEqual(ovn_charm.host_numa_nodes(), [0, 1])

    def test_ovs_numa_nodes(self):
        self.patch_sysfs()
        self.add_netdev('eth1', numa_node=1)
        self.patch_bridge_interface_map({'eth1': {}})
        self.assertEqual(self.target.ovs_numa_nodes(), [1])

    def test_ovs_numa_nodes_without_cpus(self):
        # A port on a NUMA node without CPUs, such as one only holding CXL
        # memory, has its share of CPUs taken from the other nodes.
        self.patch_sysfs(numa_nodes=4, memory_only=(3,))
        self.add_netdev('eth1', numa_node=1)
        self.add_netdev('eth3', numa_node=3)
        self.patch_bridge_interface_map({'eth1': {}, 'eth3': {}})
        self.patch_object(ovn_charm.ch_core.hookenv, 'log')
        self.assertEqual(self.target.ovs_numa_nodes(), [1])
        self.assertTrue(any('without CPUs' in c.args[0]
                            for c in self.log.call_args_list))

    def test_allocate_ovs_cpus_port_without_cpus(self):
        # Every CPU asked for is held, rather than the share of the node
        # without CPUs going missing.
        self.patch_epa(16, allocate={1: '64-71,192-199'})
        for node, cpulist in ((2, '128-191'), (3, '')):
            node_dir = os.path.join(self.sysfs, 'node', f'node{node}')
            os.makedirs(node_dir)
            with open(os.path.join(node_dir, 'cpulist'), 'w') as f:
                f.write(cpulist + '\n')
        self.add_netdev('eth1', numa_node=1)
        self.add_netdev('eth3', numa_node=3)
        self.patch_bridge_interface_map({'eth1': {}, 'eth3': {}})
        self.patch_object(ovn_charm.ch_core.hookenv, 'log')
        self.target.allocate_ovs_cpus()
        self.assertIn(('ovs-vswitchd', 1, 16),
                      [c.args for c in self.allocate_numa_cores.mock_calls])

    def test_ovs_numa_nodes_unknown(self):
        self.patch_sysfs()
        self.add_netdev('veth0')
        self.patch_bridge_interface_map({'veth0': {}})
        self.assertEqual(self.target.ovs_numa_nodes(), [0])

    def patch_epa(self, ovs_cpu_cores, allocate=None):
        """Configure ``ovs-cpu-cores`` with the EPA orchestrator installed.

        :param ovs_cpu_cores: Value for the ``ovs-cpu-cores`` option.
        :type ovs_cpu_cores: int
        :param allocate: CPUs EPA hands out per NUMA node.
        :type allocate: Optional[Dict[int,str]]
        """
        self.local_config.update({'ovs-cpu-cores': ovs_cpu_cores})
        self.target = ovn_charm.BaseOVNChassisCharm()
        self.patch_target('run')
        self.epa_available.return_value = True
        self.patch_sysfs()
        allocate = allocate or {}

        def _allocate(service_name, numa_node, num_of_cores, pool):
            return allocate.get(numa_node, '') if num_of_cores > 0 else ''

        self.patch_object(ovn_charm.epa_client, 'allocate_numa_cores',
                          side_effect=_allocate)
        self.patch_object(ovn_charm.reactive, 'set_flag')
        self.patch_object(ovn_charm.reactive, 'clear_flag')

    def read_drop_in(self):
        with open(self.cpu_affinity_drop_in) as f:
            return f.read()

    def test_configure_ovs_cpu_affinity(self):
        self.patch_epa(8, allocate={1: '136-139,392-395'})
        self.patch_target('ovs_numa_nodes', return_value=[1])
        self.assertTrue(self.target.configure_ovs_cpu_affinity())
        self.allocate_numa_cores.assert_has_calls([
            mock.call('ovs-vswitchd', 0, -1, pool='general'),
            mock.call('ovs-vswitchd', 1, 8, pool='general'),
        ])
        self.set_flag.assert_called_once_with('charm.ovn.epa-cores-held')
        self.assertEqual(self.read_drop_in(),
                         '[Service]\nCPUAffinity=136-139,392-395\n')
        self.run.assert_called_once_with('systemctl', 'daemon-reload')

    def test_configure_ovs_cpu_affinity_unchanged(self):
        self.patch_epa(8, allocate={1: '136-139,392-395'})
        self.patch_target('ovs_numa_nodes', return_value=[1])
        os.makedirs(os.path.dirname(self.cpu_affinity_drop_in))
        with open(self.cpu_affinity_drop_in, 'w') as f:
            f.write('[Service]\nCPUAffinity=136-139,392-395\n')
        self.assertFalse(self.target.configure_ovs_cpu_affinity())
        self.run.assert_not_called()

    def test_configure_ovs_cpu_affinity_numa_nodes(self):
        # Ports on both NUMA nodes share the cores between them.
        self.patch_epa(8, allocate={0: '8-11', 1: '136-139'})
        self.patch_target('ovs_numa_nodes', return_value=[0, 1])
        self.assertTrue(self.target.configure_ovs_cpu_affinity())
        self.allocate_numa_cores.assert_has_calls([
            mock.call('ovs-vswitchd', 0, 4, pool='general'),
            mock.call('ovs-vswitchd', 1, 4, pool='general'),
        ])
        self.assertEqual(self.read_drop_in(),
                         '[Service]\nCPUAffinity=8-11,136-139\n')

    def test_configure_ovs_cpu_affinity_epa_unavailable(self):
        self.patch_epa(8)
        self.epa_available.return_value = False
        os.makedirs(os.path.dirname(self.cpu_affinity_drop_in))
        with open(self.cpu_affinity_drop_in, 'w') as f:
            f.write('[Service]\nCPUAffinity=136-139,392-395\n')
        self.assertTrue(self.target.configure_ovs_cpu_affinity())
        self.allocate_numa_cores.assert_not_called()
        self.assertFalse(os.path.exists(self.cpu_affinity_drop_in))
        self.run.assert_called_once_with('systemctl', 'daemon-reload')

    def test_configure_ovs_cpu_affinity_epa_error(self):
        # Whatever EPA handed out before failing goes back, as the CPUs
        # are not used.
        self.patch_epa(8)
        self.patch_target('ovs_numa_nodes', return_value=[1])
        self.patch_object(ovn_charm.ch_core.hookenv, 'log')

        def _allocate(service_name, numa_node, num_of_cores, pool):
            if num_of_cores > 0:
                raise ovn_charm.epa_client.EPAError('out of CPUs')
            return ''

        self.allocate_numa_cores.side_effect = _allocate
        self.assertFalse(self.target.configure_ovs_cpu_affinity())
        self.allocate_numa_cores.assert_has_calls([
            mock.call('ovs-vswitchd', 0, -1, pool='general'),
            mock.call('ovs-vswitchd', 1, -1, pool='general'),
        ])
        self.clear_flag.assert_called_once_with('charm.ovn.epa-cores-held')
        self.assertFalse(os.path.exists(self.cpu_affinity_drop_in))

    def test_configure_ovs_cpu_affinity_unset_releases(self):
        self.patch_epa(0)
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.assertFalse(self.target.configure_ovs_cpu_affinity())
        self.allocate_numa_cores.assert_has_calls([
            mock.call('ovs-vswitchd', 0, -1, pool='general'),
            mock.call('ovs-vswitchd', 1, -1, pool='general'),
        ])
        self.clear_flag.assert_called_once_with('charm.ovn.epa-cores-held')

    def test_configure_ovs_cpu_affinity_unset_release_fails(self):
        # Turning pinning off must not fail the hook when EPA cannot take
        # the CPUs back right now, for example as the general pool was
        # never configured.  It is tried again on the next hook.
        self.patch_epa(0)
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.patch_object(ovn_charm.ch_core.hookenv, 'log')
        self.allocate_numa_cores.side_effect = ovn_charm.epa_client.EPAError(
            'CPU pool general is not configured')
        os.makedirs(os.path.dirname(self.cpu_affinity_drop_in))
        with open(self.cpu_affinity_drop_in, 'w') as f:
            f.write('[Service]\nCPUAffinity=136-139,392-395\n')
        self.assertTrue(self.target.configure_ovs_cpu_affinity())
        self.assertFalse(os.path.exists(self.cpu_affinity_drop_in))
        self.clear_flag.assert_not_called()

    def test_configure_ovs_cpu_affinity_unset_nothing_held(self):
        self.patch_epa(0)
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=False)
        self.assertFalse(self.target.configure_ovs_cpu_affinity())
        self.allocate_numa_cores.assert_not_called()

    def test_configure_ovs_pins_before_dpdk(self):
        # Whether ovs-vswitchd is pinned decides the DPDK lcore mask.
        self.patch_target('run')
        self.patch_target('check_if_paused', return_value=(None, None))
        self.patch_target('get_data_ip')
        self.patch_target('get_ovs_hostname')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_key')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_cert')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_ca_cert')
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        self.patch_object(ovn_charm.ch_core.host, 'service_start')
        calls = mock.MagicMock()
        for method in ('configure_ovs_cpu_affinity', 'configure_ovs_dpdk',
                       'configure_ovs_hw_offload', 'configure_ovs_doca',
                       'configure_ovs_datapath'):
            self.patch_target(method, return_value=False)
            calls.attach_mock(getattr(self, method), method)
        self.target.configure_ovs('fake-sb-conn-str', False)
        names = [c[0] for c in calls.mock_calls]
        self.assertLess(names.index('configure_ovs_cpu_affinity'),
                        names.index('configure_ovs_dpdk'))

    def test_configure_ovs_restarts_on_cpu_affinity_change(self):
        self.patch_target('configure_ovs_cpu_affinity', return_value=True)
        self.patch_target('run')
        self.patch_target('check_if_paused', return_value=(None, None))
        self.patch_target('get_data_ip')
        self.patch_target('get_ovs_hostname')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_key')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_cert')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_ca_cert')
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        self.target.configure_ovs('fake-sb-conn-str', False)
        self.service_restart.assert_called_once_with('openvswitch-switch')

    def test_custom_assess_status_last_check_not_pinned(self):
        # Pinning is best effort, so the unit keeps working, but says so.
        self.local_config.update({'ovs-cpu-cores': 16})
        self.target = ovn_charm.BaseOVNChassisCharm()
        self.epa_available.return_value = True
        self.assertEqual(
            self.target.custom_assess_status_last_check(),
            ('active', 'ovs-vswitchd is not pinned to the 16 CPUs in '
                       'ovs-cpu-cores, see the unit log.'))

    def test_custom_assess_status_last_check_without_epa(self):
        # Pinning is on by default, which says nothing about machines the
        # EPA orchestrator was not deployed to.
        self.local_config.update({'ovs-cpu-cores': 16})
        self.target = ovn_charm.BaseOVNChassisCharm()
        self.assertEqual(self.target.custom_assess_status_last_check(),
                         (None, None))

    def test_cpu_list_to_mask(self):
        self.assertEqual(ovn_charm.cpu_list_to_mask('8-11'), '0xf00')
        self.assertEqual(ovn_charm.cpu_list_to_mask('0,2-3'), '0xd')

    def write_isolated(self, isolated):
        """Isolate the CPUs in CPU list ``isolated`` with ``isolcpus``."""
        with open(os.path.join(self.sysfs, 'cpu', 'isolated'), 'w') as f:
            f.write(isolated + '\n')

    def patch_epa_pmd(self, allocate=None, datapath_types=('doca',),
                      isolated='72-79'):
        """Run a userspace datapath with the EPA orchestrator installed.

        ``pmd-cpu-set`` is set too, to show it is not used then.

        :param allocate: CPUs EPA hands out per NUMA node.
        :type allocate: Optional[Dict[int,str]]
        :param datapath_types: Datapath types ovs-vswitchd offers.
        :type datapath_types: Iterable[str]
        :param isolated: CPU list of the CPUs isolated with ``isolcpus``.
        :type isolated: str
        """
        self.local_config.update({'pmd-cpu-set': '8-11'})
        self.patch_epa(0, allocate=allocate)
        self.write_isolated(isolated)
        self.patch_target('ovs_datapath_types',
                          return_value=set(datapath_types))
        self.patch_target('ovs_numa_nodes', return_value=[1])
        self.patch_object(ovn_charm.os_context, 'OVSDPDKDeviceContext')
        self.patch_object(ovn_charm.ch_core.hookenv, 'log')

    def test_pmd_cpu_mask_epa(self):
        # On a host shared with Ceph the PMD cores come from EPA, from the
        # isolated pool, as PMD threads poll in a busy loop.  EPA refuses
        # an owner that holds CPUs in the other pool, so those go first.
        self.patch_epa_pmd(allocate={1: '72-75'})
        self.assertEqual(self.target.pmd_cpu_mask(),
                         ovn_charm.cpu_list_to_mask('72-75'))
        self.allocate_numa_cores.assert_has_calls([
            mock.call('ovs-vswitchd-pmd', 0, -1, pool='general'),
            mock.call('ovs-vswitchd-pmd', 1, -1, pool='general'),
            mock.call('ovs-vswitchd-pmd', 0, -1, pool='isolated'),
            mock.call('ovs-vswitchd-pmd', 1, 4, pool='isolated'),
        ])
        self.set_flag.assert_called_once_with(
            'charm.ovn.epa-pmd-cores-held.isolated')
        self.clear_flag.assert_called_once_with(
            'charm.ovn.epa-pmd-cores-held.general')
        self.OVSDPDKDeviceContext.assert_not_called()

    def test_pmd_cpu_mask_epa_not_isolated(self):
        # Without enough isolated CPUs the PMD threads still get CPUs
        # through EPA, so none that Ceph holds, from the general pool.
        self.patch_epa_pmd(allocate={1: '124-127'}, isolated='72-74')
        self.assertEqual(self.target.pmd_cpu_mask(),
                         ovn_charm.cpu_list_to_mask('124-127'))
        self.allocate_numa_cores.assert_has_calls([
            mock.call('ovs-vswitchd-pmd', 0, -1, pool='isolated'),
            mock.call('ovs-vswitchd-pmd', 1, -1, pool='isolated'),
            mock.call('ovs-vswitchd-pmd', 0, -1, pool='general'),
            mock.call('ovs-vswitchd-pmd', 1, 4, pool='general'),
        ])
        self.set_flag.assert_called_once_with(
            'charm.ovn.epa-pmd-cores-held.general')

    def test_pmd_cpu_mask_epa_once_per_hook(self):
        # The mask is needed both for pmd-cpu-mask and n_rxq.
        self.patch_epa_pmd(allocate={1: '72-75'})
        self.target.pmd_cpu_mask()
        calls = self.allocate_numa_cores.call_count
        self.target.pmd_cpu_mask()
        self.assertEqual(self.allocate_numa_cores.call_count, calls)

    def test_pmd_cpu_mask_epa_unavailable_cpus(self):
        # Falling back to pmd-cpu-set could put PMD threads on CPUs EPA
        # gave to Ceph, so leave the choice to Open vSwitch instead.
        self.patch_epa_pmd()

        def _allocate(service_name, numa_node, num_of_cores, pool):
            if num_of_cores > 0:
                raise ovn_charm.epa_client.EPAError('out of CPUs')
            return ''

        self.allocate_numa_cores.side_effect = _allocate
        self.assertIsNone(self.target.pmd_cpu_mask())
        self.OVSDPDKDeviceContext.assert_not_called()

    def test_pmd_cpu_mask_epa_kernel_datapath(self):
        # Moving off a userspace datapath hands the PMD cores back.
        self.patch_epa_pmd(datapath_types=('system',))
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.assertIsNone(self.target.pmd_cpu_mask())
        self.allocate_numa_cores.assert_has_calls([
            mock.call('ovs-vswitchd-pmd', 0, -1, pool='general'),
            mock.call('ovs-vswitchd-pmd', 1, -1, pool='general'),
            mock.call('ovs-vswitchd-pmd', 0, -1, pool='isolated'),
            mock.call('ovs-vswitchd-pmd', 1, -1, pool='isolated'),
        ])
        self.clear_flag.assert_has_calls([
            mock.call('charm.ovn.epa-pmd-cores-held.general'),
            mock.call('charm.ovn.epa-pmd-cores-held.isolated'),
        ])

    def patch_local_pmd(self, isolated, ovs_numa_nodes=(1,), pmd_cpu_set=None,
                        pmd_cpu_cores=4):
        """Run the ``doca`` datapath on a machine without EPA, like a DPU.

        :param isolated: CPU list of the CPUs isolated with ``isolcpus``.
        :type isolated: str
        :param ovs_numa_nodes: NUMA nodes of the physical ports.
        :type ovs_numa_nodes: Iterable[int]
        :param pmd_cpu_set: Value for the ``pmd-cpu-set`` option.
        :type pmd_cpu_set: Optional[str]
        :param pmd_cpu_cores: Value for the ``pmd-cpu-cores`` option.
        :type pmd_cpu_cores: int
        """
        self.local_config.update({'pmd-cpu-set': pmd_cpu_set,
                                  'pmd-cpu-cores': pmd_cpu_cores})
        self.target = ovn_charm.BaseOVNChassisCharm()
        self.patch_sysfs()
        self.write_isolated(isolated)
        self.patch_target('ovs_datapath_types', return_value={'doca'})
        self.patch_target('ovs_numa_nodes', return_value=list(ovs_numa_nodes))
        self.patch_object(ovn_charm.os_context, 'OVSDPDKDeviceContext')
        self.patch_object(ovn_charm.ch_core.hookenv, 'log')

    def test_pmd_cpu_mask_isolated(self):
        # Without EPA the PMD threads have the isolated CPUs to themselves.
        self.patch_local_pmd('8-15,72-79')
        self.assertEqual(self.target.pmd_cpu_mask(),
                         ovn_charm.cpu_list_to_mask('72-75'))
        self.OVSDPDKDeviceContext.assert_not_called()

    def test_pmd_cpu_mask_isolated_lcore(self):
        # DPDK runs its lcore threads on the CPUs in dpdk-lcore-mask.
        self.local_config.update({'enable-dpdk': True})
        self.patch_local_pmd('0-3,8-11', ovs_numa_nodes=(0,))
        self.OVSDPDKDeviceContext.return_value.cpu_mask.return_value = '0x1'
        self.assertEqual(self.target.pmd_cpu_mask(),
                         ovn_charm.cpu_list_to_mask('1-3,8'))

    def test_pmd_cpu_mask_isolated_numa_nodes(self):
        self.patch_local_pmd('8-15,72-79', ovs_numa_nodes=(0, 1))
        self.assertEqual(self.target.pmd_cpu_mask(),
                         ovn_charm.cpu_list_to_mask('8-9,72-73'))

    def test_pmd_cpu_mask_not_isolated(self):
        # Pinned to CPUs that are not isolated still beats the CPU Open
        # vSwitch picks itself, the first of the NUMA node, where kernel
        # housekeeping and interrupts run.  The highest numbered ones are
        # furthest from those.
        self.patch_local_pmd('')
        self.assertEqual(self.target.pmd_cpu_mask(),
                         ovn_charm.cpu_list_to_mask('124-127'))

    def test_pmd_cpu_mask_isolated_too_few(self):
        # All or nothing, so the PMD threads are not part isolated.
        self.patch_local_pmd('8-15,72-74', ovs_numa_nodes=(0, 1),
                             pmd_cpu_cores=8)
        self.assertEqual(self.target.pmd_cpu_mask(),
                         ovn_charm.cpu_list_to_mask('60-63,124-127'))

    def test_pmd_cpu_mask_too_few_cpus(self):
        self.patch_local_pmd('', pmd_cpu_cores=65)
        self.assertIsNone(self.target.pmd_cpu_mask())

    def test_pmd_cpu_mask_pmd_cpu_set(self):
        # Deprecated, but still honoured without EPA, for the DPDK
        # deployments that have it set.
        self.patch_local_pmd('8-15,72-79', pmd_cpu_set='8-11')
        self.OVSDPDKDeviceContext.return_value.pmd_cpu_mask.return_value = (
            '0xf00')
        self.assertEqual(self.target.pmd_cpu_mask(), '0xf00')
        self.assertTrue(any('deprecated' in c.args[0]
                            for c in self.log.call_args_list))

    def test_custom_assess_status_last_check_pmd_not_pinned_without_epa(
            self):
        self.patch_open_vswitch({})
        self.assertEqual(
            self.target.custom_assess_status_last_check(),
            ('active', 'PMD threads are not pinned to the 4 CPUs in '
                       'pmd-cpu-cores, see the unit log.'))

    def patch_open_vswitch(self, other_config):
        """Present a ``doca`` capable Open_vSwitch row."""
        self.patch_object(ovn_charm.ch_core.host, 'service_running',
                          return_value=True)
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'datapath_types': ['system', 'doca'],
            'other_config': other_config,
        }]
        self.SimpleOVSDB.return_value = ovsdb

    def test_custom_assess_status_last_check_pmd_not_pinned(self):
        self.epa_available.return_value = True
        self.patch_open_vswitch({})
        self.assertEqual(
            self.target.custom_assess_status_last_check(),
            ('active', 'PMD threads are not pinned to the 4 CPUs in '
                       'pmd-cpu-cores, see the unit log.'))

    def test_custom_assess_status_last_check_pmd_pinned(self):
        self.epa_available.return_value = True
        self.patch_open_vswitch({'pmd-cpu-mask': '0xf0'})
        self.assertEqual(self.target.custom_assess_status_last_check(),
                         (None, None))

    def test_configure_ovs_doca_not_ours(self):
        # The offload provider of a host that had OVS-DOCA before the charm
        # arrived is not ours to turn off.
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=False)
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {'doca-init': 'true'}}]
        self.SimpleOVSDB.return_value = ovsdb
        self.assertFalse(self.target.configure_ovs_doca())
        ovsdb.open_vswitch.set.assert_not_called()
        ovsdb.open_vswitch.remove.assert_not_called()

    def test_configure_ovs_doca_relinquishes_ownership(self):
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.patch_object(ovn_charm.reactive, 'clear_flag')
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {'doca-init': 'true'}}]
        self.SimpleOVSDB.return_value = ovsdb
        self.target.options.enable_doca = True
        self.target.configure_ovs_doca()
        self.clear_flag.assert_called_once_with('charm.ovn.doca-managed')

    def test_purge_packages_doca_not_ours(self):
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=False)
        self.assertNotIn('doca-networking', self.target.purge_packages)

    def test_run(self):
        self.patch_object(ovn_charm.subprocess, 'run')
        self.patch_object(ovn_charm.ch_core.hookenv, 'log')
        self.target.run('some', 'args')
        self.run.assert_called_once_with(
            ('some', 'args'),
            stdout=ovn_charm.subprocess.PIPE,
            stderr=ovn_charm.subprocess.STDOUT,
            check=True,
            universal_newlines=True)

    def test_get_certificate_requests(self):
        self.patch_target('get_ovs_hostname')
        self.get_ovs_hostname.return_value = 'fake-ovs-hostname'
        self.assertDictEqual(
            self.target.get_certificate_requests(),
            {'fake-ovs-hostname': {'sans': []}})

    def test_configure_tls(self):
        self.patch_target('get_certs_and_keys')
        self.get_certs_and_keys.return_value = [
            {
                'cert': 'notformefakecert',
                'key': 'notformefakekey',
                'cn': 'notformefakecn',
                'ca': 'notformefakeca',
                'chain': 'notformefakechain',
            },
            {
                'cert': 'fakecert',
                'key': 'fakekey',
                'cn': 'fakecn',
                'ca': 'fakeca',
                'chain': 'fakechain',
            }
        ]
        self.patch_target('ovn_sysconfdir')
        self.ovn_sysconfdir.return_value = '/etc/path'
        self.patch_target('get_ovs_hostname')
        self.get_ovs_hostname.return_value = 'fakecn'
        with mock.patch('builtins.open', create=True) as mocked_open:
            mocked_file = mock.MagicMock(spec=io.FileIO)
            mocked_open.return_value = mocked_file
            self.target.configure_cert = mock.MagicMock()
            self.target.run = mock.MagicMock()
            self.target.configure_tls()
            mocked_open.assert_called_once_with(
                '/etc/path/charmname.crt', 'w')
            mocked_file.__enter__().write.assert_called_once_with(
                'fakeca\nfakechain')
            self.target.configure_cert.assert_called_once_with(
                '/etc/path',
                'fakecert',
                'fakekey',
                cn='host')

    def test_configure_tls_not_ready(self):
        self.patch_target('get_certs_and_keys')
        self.get_certs_and_keys.return_value = None
        self.target.configure_cert = mock.MagicMock()
        self.target.configure_tls()
        self.target.configure_cert.assert_not_called()

    def test__format_addr(self):
        self.assertEqual('1.2.3.4', self.target._format_addr('1.2.3.4'))
        self.assertEqual(
            '[2001:db8::42]', self.target._format_addr('2001:db8::42'))
        with self.assertRaises(ValueError):
            self.target._format_addr('999.999.999.999')
        with self.assertRaises(ValueError):
            self.target._format_addr('2001:db8::g')

    def test_get_data_ip(self):
        self.patch_object(ovn_charm.ch_core.hookenv, 'network_get')
        self.network_get.return_value = {
            'bind-addresses': [
                {
                    'mac-address': 'fa:16:3e:68:e7:dd',
                    'interface-name': 'ens3',
                    'addresses': [
                        {
                            'hostname': '',
                            'address': '10.5.0.102',
                            'cidr': '10.5.0.0/16',
                        }
                    ]
                }
            ]
        }
        self.assertEqual(self.target.get_data_ip(), '10.5.0.102')

    def test_get_ovs_hostname(self):
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        opvs = mock.MagicMock()
        opvs.open_vswitch.__iter__.return_value = [
            {'external_ids': {'hostname': 'fake-ovs-hostname'}}]
        self.SimpleOVSDB.return_value = opvs
        self.assertEqual(self.target.get_ovs_hostname(), 'fake-ovs-hostname')

    def test_configure_ovs(self):
        self.patch_target('run')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_key')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_cert')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_ca_cert')
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        self.patch_target('get_data_ip')
        self.get_data_ip.return_value = 'fake-data-ip'
        self.patch_target('get_ovs_hostname')
        self.get_ovs_hostname.return_value = 'fake-ovs-hostname'
        self.patch_target('check_if_paused')
        self.check_if_paused.return_value = ('some', 'reason')
        self.target.configure_ovs('fake-sb-conn-str', True)
        self.run.assert_not_called()
        self.service_restart.assert_not_called()
        self.check_if_paused.return_value = (None, None)
        self.target.configure_ovs('fake-sb-conn-str', False)
        self.run.assert_has_calls([
            mock.call('ovs-vsctl', '--no-wait', 'set-ssl',
                      mock.ANY, mock.ANY, mock.ANY),
            mock.call(
                'ovs-vsctl',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-encap-type=geneve',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-encap-ip=fake-data-ip',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:system-id=fake-ovs-hostname',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-remote=fake-sb-conn-str',
                '--', 'set', 'open-vswitch', '.',
                'external_ids:ovn-match-northd-version=False',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-monitor-all=True',
            ),
        ])
        self.service_restart.assert_not_called()
        self.run.reset_mock()
        self.enable_openstack.return_value = True
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        managers = mock.MagicMock()
        self.SimpleOVSDB.return_value = managers
        self.target.configure_ovs('fake-sb-conn-str', True)
        managers.manager.find.assert_called_once_with(
            'target="ptcp:6640:127.0.0.1"')
        self.run.assert_has_calls([
            mock.call('ovs-vsctl', '--no-wait', 'set-ssl',
                      mock.ANY, mock.ANY, mock.ANY),
            mock.call(
                'ovs-vsctl',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-encap-type=geneve',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-encap-ip=fake-data-ip',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:system-id=fake-ovs-hostname',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-remote=fake-sb-conn-str',
                '--', 'set', 'open-vswitch', '.',
                'external_ids:ovn-match-northd-version=False',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-monitor-all=True',
            ),
            mock.call('ovs-vsctl', '--id', '@manager',
                      'create', 'Manager', 'target="ptcp:6640:127.0.0.1"',
                      '--', 'add', 'Open_vSwitch', '.', 'manager_options',
                      '@manager'),
        ])
        assert self.service_restart.called

    def test_configure_ovs_version_pinning(self):
        self.local_config.update({'enable-version-pinning': True})
        self.target = ovn_charm.BaseOVNChassisCharm()
        self.patch_target('run')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_key')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_cert')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_ca_cert')
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        self.patch_target('get_data_ip')
        self.get_data_ip.return_value = 'fake-data-ip'
        self.patch_target('get_ovs_hostname')
        self.get_ovs_hostname.return_value = 'fake-ovs-hostname'
        self.patch_target('check_if_paused')
        self.check_if_paused.return_value = (None, None)
        self.target.configure_ovs('fake-sb-conn-str', False)
        self.run.assert_has_calls([
            mock.call('ovs-vsctl', '--no-wait', 'set-ssl',
                      mock.ANY, mock.ANY, mock.ANY),
            mock.call(
                'ovs-vsctl',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-encap-type=geneve',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-encap-ip=fake-data-ip',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:system-id=fake-ovs-hostname',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-remote=fake-sb-conn-str',
                '--', 'set', 'open-vswitch', '.',
                'external_ids:ovn-match-northd-version=True',
                '--', 'set', 'open-vswitch', '.',
                'external-ids:ovn-monitor-all=True',
            ),
        ])

    def test_render_nrpe(self):
        self.patch_object(ovn_charm.nrpe, 'NRPE')
        self.patch_object(ovn_charm.nrpe, 'add_init_service_checks')
        self.target.render_nrpe()
        self.add_init_service_checks.assert_has_calls([
            mock.call().add_init_service_checks(
                mock.ANY,
                ['ovn-controller', 'ovs-vswitchd', 'ovsdb-server'],
                mock.ANY
            ),
        ])
        self.NRPE.assert_has_calls([
            mock.call().write(),
        ])

    def test_configure_bridges(self):
        self.patch_object(ovn_charm.os_context, 'BridgePortInterfaceMap')
        dict_bpi = {
            'br-provider': {  # bridge
                'eth0': {     # port
                              # interface(s) with interface data
                    'eth0': {'data': 'fake'},
                },
            },
            'br-other': {
                'eth5': {
                    'eth5': {'data': 'fake'},
                },
            },
            'br-int': {
                'someport': {
                    'someport': {'data': 'fake'},
                },
            },
        }
        mock_bpi = mock.MagicMock()
        mock_bpi.items.return_value = dict_bpi.items()
        mock_bpi.__iter__.side_effect = lambda: iter(dict_bpi)
        mock_bpi.__contains__.side_effect = dict_bpi.__contains__
        mock_bpi.__getitem__.side_effect = lambda x: dict_bpi.__getitem__(x)
        mock_bpi.get_ifdatamap.side_effect = lambda x, y: {
            k: v for k, v in dict_bpi[x][y].items()}
        self.BridgePortInterfaceMap.return_value = mock_bpi
        self.patch_object(ovn_charm.os_context, 'BondConfig')
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')

        ovsdb = mock.MagicMock()
        ovsdb.bridge.find.side_effect = [
            [
                {'name': 'delete-bridge'},
                {'name': 'br-other'},
                {'name': 'br-int'},
            ],
            StopIteration,
        ]
        ovsdb.port.find.return_value = [{'name': 'delete-port'}]
        self.SimpleOVSDB.return_value = ovsdb

        self.patch_object(ovn_charm.OVNConfigurationAdapter,
                          'card_serial_number', new_callable=mock.PropertyMock)
        self.card_serial_number.return_value = 'c4rd-53r14l'

        self.patch_object(ovn_charm.ch_ovs, 'del_bridge')
        self.patch_object(ovn_charm.ch_ovs, 'del_bridge_port')
        self.patch_object(ovn_charm.ch_ovs, 'add_bridge')
        self.patch_object(ovn_charm.ch_ovs, 'get_bridge_ports')
        self.get_bridge_ports().__iter__.return_value = []
        self.patch_object(ovn_charm.ch_ovs, 'add_bridge_port')
        self.patch_target('check_if_paused')
        self.check_if_paused.return_value = ('some', 'reason')
        self.patch_target('_get_port_type')
        self._get_port_type.return_value = ''
        self.target.configure_bridges()
        self.BridgePortInterfaceMap.assert_not_called()
        self.check_if_paused.return_value = (None, None)
        self.target.configure_bridges()
        self.BridgePortInterfaceMap.assert_called_once_with(
            bridges_key='bridge-interface-mappings')
        # br-int should not be deleted when not in config, even when managed
        self.del_bridge.assert_called_once_with('delete-bridge')
        # since we manage it we will delete non-existant managed ports in it
        self.del_bridge_port.assert_has_calls([
            mock.call('br-other', 'delete-port', linkdown=True),
            mock.call('br-int', 'delete-port', linkdown=True),
        ])
        # br-int will always be added/updated regardless of presence in config
        self.add_bridge.assert_has_calls([
            mock.call(
                'br-int',
                brdata={
                    'external-ids': {'charm-ovn-chassis': 'managed'},
                    'datapath-type': 'system',
                    'protocols': 'OpenFlow13,OpenFlow15',
                    'fail-mode': 'secure',
                    'other-config': {'disable-in-band': 'true'},
                }),
            mock.call(
                'br-provider',
                brdata={
                    'external-ids': {'charm-ovn-chassis': 'managed'},
                    'datapath-type': 'system',
                    'protocols': 'OpenFlow13,OpenFlow15',
                    'fail-mode': 'standalone',
                }),
            mock.call(
                'br-other',
                brdata={
                    'external-ids': {'charm-ovn-chassis': 'managed'},
                    'datapath-type': 'system',
                    'protocols': 'OpenFlow13,OpenFlow15',
                    'fail-mode': 'standalone',
                }),
        ], any_order=True)
        self.add_bridge_port.assert_has_calls([
            mock.call(
                'br-provider', 'eth0', ifdata={
                    'data': 'fake',
                    'external-ids': {'charm-ovn-chassis': 'br-provider'}},
                linkup=True, promisc=None, portdata={
                    'external-ids': {'charm-ovn-chassis': 'br-provider'}}),
            mock.call(
                'br-other', 'eth5', ifdata={
                    'data': 'fake',
                    'external-ids': {'charm-ovn-chassis': 'br-other'}},
                linkup=True, promisc=None, portdata={
                    'external-ids': {'charm-ovn-chassis': 'br-other'}}),
        ], any_order=True)
        ovsdb.open_vswitch.set.assert_has_calls([
            mock.call('.', 'external_ids:ovn-bridge-mappings',
                      'other:br-other,provider:br-provider'),
            mock.call('.', 'external_ids:ovn-cms-options',
                      'enable-chassis-as-gw,card-serial-number=c4rd-53r14l'),
        ], any_order=True)

    def test_wrong_configure_bridges(self):
        self.patch_object(ovn_charm.os_context, 'BridgePortInterfaceMap')
        self.BridgePortInterfaceMap.side_effect = ValueError()
        self.patch_target('check_if_paused')
        self.check_if_paused.return_value = (None, None)
        self.assertEqual(self.target.custom_assess_status_last_check(),
                         (None, None))
        self.target.configure_bridges()
        self.BridgePortInterfaceMap.assert_called_once_with(
            bridges_key='bridge-interface-mappings')

        expected_msg = ('"Wrong format for bridge-interface-mappings. '
                        'Expected format is space-delimited list of '
                        'key-value pairs. Ex: "br-internet:00:00:5e:00:00:42 '
                        'br-provider:enp3s0f0""')

        self.assertEqual(
            self.target.custom_assess_status_last_check(),
            ('blocked', f'{self.target.bridges_key}: {expected_msg}'))

    def test_empty_configure_bridges(self):
        self.patch_object(ovn_charm.os_context, 'BridgePortInterfaceMap')
        self.BridgePortInterfaceMap.return_value = {}

        self.patch_target('check_if_paused')
        self.check_if_paused.return_value = (None, None)
        self.assertEqual(self.target.custom_assess_status_last_check(),
                         (None, None))
        self.target.configure_bridges()
        self.BridgePortInterfaceMap.assert_called_once_with(
            bridges_key='bridge-interface-mappings')

        self.assertEqual(
            self.target.custom_assess_status_last_check(),
            (None, None)
        )

    def test_wrong_vpd_spec(self):
        self.target.options.vpd_device_spec = '{'
        self.patch_target('check_if_paused')
        self.check_if_paused.return_value = (None, None)
        self.assertEqual(self.target.custom_assess_status_last_check(),
                         (None, None))
        self.assertIsNone(self.target.options.card_serial_number)

        self.assertEqual(
            self.target.custom_assess_status_last_check(),
            ('blocked',
             'vpd-device-spec: "Invalid JSON provided for VPD device spec: {"')
        )

    def test_wrong_multiple(self):
        """Test rendering of multiple config validation errors"""
        self.target.options.vpd_device_spec = '{'
        self.patch_target('check_if_paused')
        self.check_if_paused.return_value = (None, None)
        self.assertEqual(self.target.custom_assess_status_last_check(),
                         (None, None))
        self.assertIsNone(self.target.options.card_serial_number)

        self.patch_object(ovn_charm.os_context, 'BridgePortInterfaceMap')
        self.BridgePortInterfaceMap.side_effect = ValueError()
        self.target.configure_bridges()

        self.assertEqual(
            self.target.custom_assess_status_last_check(),
            ('blocked',
             'vpd-device-spec: "Invalid JSON provided for VPD device spec: {",'
             ' bridge-interface-mappings: "Wrong format for'
             ' bridge-interface-mappings. Expected format is space-delimited'
             ' list of key-value pairs. Ex: "br-internet:00:00:5e:00:00:42'
             ' br-provider:enp3s0f0""')
        )

    def test_states_to_check(self):
        self.maxDiff = None
        expect = collections.OrderedDict([
            ('certificates', [
                ('certificates.available', 'blocked',
                 "'certificates' missing"),
                ('certificates.server.certs.available',
                 'waiting',
                 "'certificates' awaiting server certificate data")]),
            ('ovsdb', [
                ('ovsdb.connected', 'blocked', "'ovsdb' missing"),
                ('ovsdb.available', 'waiting', "'ovsdb' incomplete")]),

        ])
        self.assertDictEqual(self.target.states_to_check(), expect)

    def test_resume(self):
        self.patch_target('run_pause_or_resume')
        self.patch_object(ovn_charm.os, 'execl')
        self.patch_object(ovn_charm.ch_core.hookenv, 'charm_dir')
        self.charm_dir.return_value = '/some/path'
        self.target.resume()
        self.execl.assert_called_once_with(
            '/usr/bin/env', 'python3', '/some/path/hooks/config-changed')

    def test_purge_packages(self):
        # The DOCA packages are purged when they are ours and no longer
        # wanted.
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.assertEqual(
            self.target.purge_packages,
            [
                'mlnx-switchdev-mode',
                'sriov-netplan-shim',
                'openvswitch-switch-dpdk',
                'doca-networking',
                'mlnx-fw-updater',
            ])

    def test_install(self):
        self.patch_target('configure_source')
        self.patch_target('run')
        self.patch_target('update_api_ports')
        self.patch_target('render_configs')
        self.patch_target('remove_obsolete_packages')
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        flags = {
            'charm.installed': False,
            'config.changed.enable-dpdk': True,
        }
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          side_effect=lambda flag: flags.get(flag, False))
        self.target.install()
        self.render_configs.assert_called_once_with(
            ['/etc/default/openvswitch-switch'])
        self.service_restart.assert_called_once_with(
            'openvswitch-switch')

        # Check that Open vSwitch is restarted when DPDK is disabled
        self.remove_obsolete_packages.return_value = True
        self.service_restart.reset_mock()
        self.target.install()
        self.service_restart.assert_has_calls([
            mock.call('openvswitch-switch'),
            mock.call('openvswitch-switch'),
        ])

    def test_reconcile_open_vswitch(self):
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {
                'keep': 'me',
                'change': 'old-value',
                'remove': 'me',
            },
        }]
        self.SimpleOVSDB.return_value = ovsdb
        self.assertTrue(self.target._reconcile_open_vswitch('other_config', (
            ('keep', 'me'),
            ('change', 'new-value'),
            ('remove', None),
            ('never-was-there', None),
        )))
        ovsdb.open_vswitch.set.assert_called_once_with(
            '.', 'other_config:change', 'new-value')
        ovsdb.open_vswitch.remove.assert_called_once_with(
            '.', 'other_config', 'remove')

    def test_reconcile_open_vswitch_idempotent(self):
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'external_ids': {'something': 'set'}}]
        self.SimpleOVSDB.return_value = ovsdb
        self.assertFalse(self.target._reconcile_open_vswitch('external_ids', (
            ('something', 'set'),)))
        ovsdb.open_vswitch.set.assert_not_called()
        ovsdb.open_vswitch.remove.assert_not_called()

    def test_configure_ovs_hw_offload(self):
        # Confirm that config is removed when HW offload is disabled
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {
                'hw-offload': 'true',
                'max-idle': '30000',
                'hw-offload-ct-ipv6-enabled': 'true',
            },
        }]
        self.SimpleOVSDB.return_value = ovsdb
        self.assertTrue(self.target.configure_ovs_hw_offload())
        ovsdb.open_vswitch.remove.assert_has_calls([
            mock.call('.', 'other_config', 'hw-offload'),
            mock.call('.', 'other_config', 'max-idle'),
            mock.call('.', 'other_config', 'hw-offload-ct-ipv6-enabled'),
        ])

        # Confirm that we don't request restart when nothing changed
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {'some-other-key-we-dont-care-about': 42}}]
        self.assertFalse(self.target.configure_ovs_hw_offload())

    def test_configure_ovs_dpdk(self):
        # Confirm that config is removed when DPDK is disabled
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        opvs = mock.MagicMock()
        self.SimpleOVSDB.return_value = opvs

        # Existing config, confirm restart and values removed as expected
        opvs.open_vswitch.__iter__.return_value = [
            {'other_config': {
                'dpdk-lcore-mask': '0x42',
                'dpdk-socket-mem': '1024,1024',
                'dpdk-init': 'true',
                'dpdk-extra': '-a 0000:42:01.0',
                'pmd-cpu-mask': '0xaf009d',
            }}]
        self.assertTrue(self.target.configure_ovs_dpdk())
        opvs.open_vswitch.remove.assert_has_calls([
            mock.call('.', 'other_config', 'dpdk-lcore-mask'),
            mock.call('.', 'other_config', 'dpdk-socket-mem'),
            mock.call('.', 'other_config', 'dpdk-init'),
            mock.call('.', 'other_config', 'dpdk-extra'),
            mock.call('.', 'other_config', 'pmd-cpu-mask'),
        ])

        opvs.open_vswitch.__iter__.return_value = [{
            'other_config': {'some-other-key-we-dont-care-about': 42}}]
        self.assertFalse(self.target.configure_ovs_dpdk())

    def test_configure_iptables_rules_not_exist(self):
        # Confirm that iptables rules are being added when it is absent
        # in the environment
        self.patch('charms.ovn_charm.BaseOVNChassisCharm.run',
                   name="run")

        def dummy_run(*args):
            if args[3] == '-C':
                raise subprocess.CalledProcessError(1, "dummy")
            return subprocess.CompletedProcess("dummy-args", 0)

        self.run.side_effect = dummy_run
        self.target.configure_iptables_rules()
        self.run.assert_has_calls([
            mock.call('iptables', '-t', 'raw', '-C', "PREROUTING",
                      '-p', 'udp', '--dport', '6081', '-j', 'NOTRACK'),
            mock.call('iptables', '-t', 'raw', '-A', "PREROUTING",
                      '-p', 'udp', '--dport', '6081', '-j', 'NOTRACK'),
            mock.call('iptables', '-t', 'raw', '-C', "OUTPUT", '-p',
                      'udp', '--dport', '6081', '-j', 'NOTRACK'),
            mock.call('iptables', '-t', 'raw', '-A', "OUTPUT", '-p',
                      'udp', '--dport', '6081', '-j', 'NOTRACK'),
        ], any_order=False)
        assert 4 == self.run.call_count

    def test_configure_iptables_rules_already_exist(self):
        # Confirm that iptables rules are not being added when rules
        # already present in the environment
        self.patch('charms.ovn_charm.BaseOVNChassisCharm.run',
                   name="run")

        def dummy_run(*args):
            return subprocess.CompletedProcess("dummy-args", 0)

        self.run.side_effect = dummy_run
        self.target.configure_iptables_rules()
        self.run.assert_has_calls([
            mock.call('iptables', '-t', 'raw', '-C', "PREROUTING",
                      '-p', 'udp', '--dport', '6081', '-j', 'NOTRACK'),
            mock.call('iptables', '-t', 'raw', '-C', "OUTPUT", '-p',
                      'udp', '--dport', '6081', '-j', 'NOTRACK'),
        ])
        assert 2 == self.run.call_count

    def test__get_port_type(self):
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.interface.__getitem__.return_value = {
            'type': '',
        }
        self.SimpleOVSDB.return_value = ovsdb
        # Confirm that retrieving type for port with single interface works
        record = uuid.uuid4()
        self.assertEqual(
            '',
            self.target._get_port_type({'interfaces': record}))
        ovsdb.interface.__getitem__.assert_called_once_with(record)
        ovsdb.reset_mock()

        # Confirm that retrieving type for port with multiple interfaces works
        record1 = uuid.uuid4()
        record2 = uuid.uuid4()
        self.assertEqual(
            '',
            self.target._get_port_type({'interfaces': [record1, record2]}))
        ovsdb.interface.__getitem__.assert_has_calls([
            mock.call(record1),
            mock.call(record2),
        ])
        self.assertEqual(
            2,
            ovsdb.interface.__getitem__.call_count)

        # Confirm that port with interfaces of different type raises an error
        ovsdb.interface.__getitem__.return_value = None
        ovsdb.interface.__getitem__.side_effect = [
            {'type': ''},
            {'type': 'dpdk'},
        ]
        with self.assertRaises(RuntimeError):
            self.target._get_port_type(
                {'_uuid': 'fake-uuid', 'interfaces': [record1, record2]})

    def test__should_linkdown(self):
        # enable-dpdk = False
        self.patch_target('_get_port_type')
        # Normal port with interfaces that should be bound to kernel driver
        self._get_port_type.return_value = ''
        self.assertTrue(self.target._should_linkdown('fake-port'))
        # DPDK port with interfaces that should not be bound to kernel driver
        self._get_port_type.return_value = 'dpdk'
        self.assertFalse(self.target._should_linkdown('fake-port'))

    def test_ovn_upgrade_available(self):
        self.patch_target('configure_source')
        self.patch_target('get_package_version')
        self.get_package_version.side_effect = ['20.03.0', '22.03.0']
        self.patch_object(ovn_charm.ch_fetch.apt_pkg, 'version_compare')
        self.version_compare.return_value = 1
        self.assertTrue(self.target.ovn_upgrade_available())
        self.version_compare.assert_called_once_with('22.03.0', '20.03.0')
        self.get_package_version.side_effect = ['20.03.0', '22.03.0']
        self.version_compare.return_value = 0
        self.assertFalse(self.target.ovn_upgrade_available())

    def test_upgrade_if_available(self):
        self.patch_target('ovn_upgrade_available')
        self.patch_target('do_openstack_pkg_upgrade')
        self.patch_target('render_with_interfaces')
        # No upgrade available
        self.target.upgrade_if_available('fake-interface-list')
        self.assertFalse(self.do_openstack_pkg_upgrade.called)
        self.assertFalse(self.render_with_interfaces.called)

        # Upgrade available
        self.ovn_upgrade_available.return_value = True
        self.target.upgrade_if_available('fake-interface-list')
        self.do_openstack_pkg_upgrade.assert_called_once_with(
            upgrade_openstack=False)
        self.render_with_interfaces.assert_called_once_with(
            'fake-interface-list')

    def test_assess_exporter_no_channel_installed(self):
        self.patch_object(ovn_charm.snap, 'is_installed')
        self.patch_object(ovn_charm.snap, 'install')
        self.patch_object(ovn_charm.snap, 'remove')
        self.patch_object(ovn_charm.snap, 'refresh')

        self.is_installed.return_value = True

        self.target.assess_exporter()
        self.remove.assert_called_once_with('prometheus-ovs-exporter')
        self.install.assert_not_called()
        self.refresh.assert_not_called()

    def test_assess_exporter_no_channel_not_installed(self):
        self.patch_object(ovn_charm.snap, 'is_installed')
        self.patch_object(ovn_charm.snap, 'install')
        self.patch_object(ovn_charm.snap, 'remove')
        self.patch_object(ovn_charm.snap, 'refresh')

        self.is_installed.return_value = False

        self.target.assess_exporter()
        self.install.assert_not_called()
        self.refresh.assert_not_called()
        self.remove.assert_not_called()


class TestOVNChassisCharmOvsExporter(Helper):

    def setUp(self):
        super().setUp(config={
            'ovs-exporter-channel': 'stable',
        })

    def test_assess_exporter_fresh_install(self):
        self.patch_object(ovn_charm.snap, 'is_installed')
        self.patch_object(ovn_charm.snap, 'install')
        self.patch_object(ovn_charm.snap, 'remove')
        self.patch_object(ovn_charm.snap, 'refresh')

        self.is_installed.return_value = False

        self.target.assess_exporter()

        self.install.assert_called_once_with(
            'prometheus-ovs-exporter',
            channel='stable')
        self.remove.assert_not_called()
        self.refresh.assert_not_called()

    def test_assess_exporter_refresh(self):
        self.patch_object(ovn_charm.snap, 'is_installed')
        self.patch_object(ovn_charm.snap, 'install')
        self.patch_object(ovn_charm.snap, 'remove')
        self.patch_object(ovn_charm.snap, 'refresh')

        self.is_installed.return_value = True

        self.target.assess_exporter()

        self.refresh.assert_called_once_with(
            'prometheus-ovs-exporter',
            channel='stable')
        self.install.assert_not_called()
        self.remove.assert_not_called()

    def test_restart_exporter_inactive(self):
        """Test restarting OVS exporter when it's currently inactive."""
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        self.patch_object(ovn_charm.ch_core.host, 'service_running')
        self.service_running.return_value = False

        self.target.restart_exporter(only_inactive=True)
        self.service_restart.assert_called_once_with(
            self.target.exporter_service)

    def test_no_restart_exporter_active(self):
        """Test exporter not getting restarted if it's already running."""
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        self.patch_object(ovn_charm.ch_core.host, 'service_running')
        self.service_running.return_value = True

        self.target.restart_exporter(only_inactive=True)
        self.service_restart.assert_not_called()

    def test_force_restart_exporter(self):
        """Test restarting OVS exporter regardless of it's current state."""
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        self.patch_object(ovn_charm.ch_core.host, 'service_running')
        self.service_running.return_value = True

        self.target.restart_exporter(only_inactive=False)
        self.service_restart.assert_called_once_with(
            self.target.exporter_service)


class TestSRIOVOVNChassisCharm(Helper):

    def setUp(self):
        super().setUp(config={
            'enable-hardware-offload': False,
            'enable-sriov': True,
            'install-doca': False,
            'enable-doca': False,
            'enable-dpdk': False,
            'bridge-interface-mappings': 'br-ex:eth0',
            'ovn-bridge-mappings': 'physnet2:br-ex',
            'ovn-source': 'distro',
        }, is_flag_set_return_value=True)
        self.enable_openstack.return_value = True

    def test__init__(self):
        self.maxDiff = None
        self.assertEqual(self.target.packages, [
            'ovn-host',
            'neutron-sriov-agent',
            'neutron-ovn-metadata-agent',
        ])
        self.assertDictEqual(self.target.restart_map, {
            '/etc/netplan/150-charm-ovn.yaml': [],
            '/etc/default/openvswitch-switch': [],
            '/etc/neutron/neutron.conf': ['neutron-sriov-agent'],
            '/etc/neutron/plugins/ml2/sriov_agent.ini': [
                'neutron-sriov-agent'],
            '/etc/openvswitch/system-id.conf': [],
            '/etc/neutron/neutron_ovn_metadata_agent.ini': [
                'neutron-ovn-metadata-agent']
        })
        self.assertEqual(self.target.group, 'neutron')
        self.assertEqual(
            self.target.required_relations,
            ['certificates', 'ovsdb', 'amqp'])

    def test_install(self):
        self.patch_target('configure_source')
        self.patch_target('run')
        self.patch_target('update_api_ports')
        self.patch_target('render_configs')
        self.patch_target('remove_obsolete_packages')
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=False)
        self.patch_object(ovn_charm.ch_core.hookenv, 'config')
        self.config.return_value = None
        self.target.install()
        self.render_configs.assert_called_once_with(
            ['/etc/default/openvswitch-switch'])
        self.service_restart.assert_called_once_with(
            'openvswitch-switch')


class TestDOCAOVNChassisCharm(Helper):

    def setUp(self):
        super().setUp(config={
            'enable-hardware-offload': True,
            'enable-sriov': False,
            'enable-dpdk': False,
            'install-doca': True,
            'enable-doca': True,
            'doca-url': 'https://example.com/doca-host.deb',
            'bridge-interface-mappings': 'br-data:bond0',
            'ovn-bridge-mappings': 'physnet1:br-data',
            'prefer-chassis-as-gw': False,
            'ovn-monitor-all': False,
            'enable-version-pinning': False,
            'vpd-device-spec': '',
            'ovn-source': 'distro',
            'pmd-cpu-set': None,
            'ovs-cpu-cores': 0,
            'pmd-cpu-cores': 4,
        })

    def test_packages(self):
        self.assertEqual(self.target.packages, [
            'ovn-host', 'doca-networking', 'mlnx-fw-updater'])

    def test_purge_packages(self):
        # The DOCA packages are only purged when they are not wanted.
        self.assertNotIn('doca-networking', self.target.purge_packages)

    def test_ovs_datapath_types(self):
        self.patch_datapath_types(['doca', 'netdev', 'system'])
        self.assertEqual(self.target.ovs_datapath_types(),
                         {'doca', 'netdev', 'system'})

    def test_ovs_datapath_types_single_value(self):
        # SimpleOVSDB has no schema knowledge and collapses a single valued
        # set column to a plain string.
        self.patch_datapath_types('system')
        self.assertEqual(self.target.ovs_datapath_types(), {'system'})

    def test_ovs_datapath_types_empty_table(self):
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = []
        self.SimpleOVSDB.return_value = ovsdb
        self.assertEqual(self.target.ovs_datapath_types(), set())

    def test_datapath_type(self):
        self.patch_datapath_types(['system', 'netdev', 'doca'])
        self.assertEqual(self.target.datapath_type, 'doca')

    def test_datapath_type_awaiting_reboot(self):
        # The DOCA kernel modules only take effect on a fresh boot, and
        # claiming a datapath ovs-vswitchd cannot open would leave br-int
        # unable to instantiate.
        self.patch_datapath_types(['system', 'netdev'])
        self.assertEqual(self.target.datapath_type, 'system')

    def test_custom_assess_status_last_check(self):
        self.patch_datapath_types(['system', 'netdev', 'doca'])
        self.patch_object(ovn_charm.ch_core.host, 'service_running',
                          return_value=True)
        self.patch_target('hugepages_reserved', return_value={1048576: 16})
        self.patch_target('datapath_type_pending', return_value=False)
        self.patch_target('applied_pmd_cpu_mask', return_value='0xf0')
        self.assertEqual(self.target.custom_assess_status_last_check(),
                         (None, None))

    def test_hugepages_reserved(self):
        self.patch_object(ovn_charm.glob, 'glob', return_value=[
            '/sys/kernel/mm/hugepages/hugepages-1048576kB'])
        with mock.patch('builtins.open', mock.mock_open(read_data='16\n')):
            self.assertEqual(self.target.hugepages_reserved(), {1048576: 16})

    def test_hugepages_reserved_none(self):
        # A pool exists for the size but nothing is reserved in it.
        self.patch_object(ovn_charm.glob, 'glob', return_value=[
            '/sys/kernel/mm/hugepages/hugepages-2048kB'])
        with mock.patch('builtins.open', mock.mock_open(read_data='0\n')):
            self.assertEqual(self.target.hugepages_reserved(), {})

    def test_custom_assess_status_last_check_without_hugepages(self):
        self.patch_datapath_types(['system', 'doca'])
        self.patch_object(ovn_charm.ch_core.host, 'service_running',
                          return_value=True)
        self.patch_target('hugepages_reserved', return_value={})
        status, message = self.target.custom_assess_status_last_check()
        self.assertEqual(status, 'blocked')
        self.assertIn('hugepages', message)

    def test_custom_assess_status_last_check_awaiting_reboot(self):
        self.patch_datapath_types(['system', 'netdev'])
        self.patch_object(ovn_charm.ch_core.host, 'service_running',
                          return_value=True)
        status, message = self.target.custom_assess_status_last_check()
        self.assertEqual(status, 'blocked')
        self.assertIn('reboot', message)

    def test_custom_assess_status_last_check_no_database(self):
        # Probing the datapath types requires a database to talk to.
        self.patch_object(ovn_charm.ch_core.host, 'service_running',
                          return_value=False)
        self.assertEqual(self.target.custom_assess_status_last_check(),
                         (None, None))

    def test_configure_ovs_doca(self):
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{'other_config': {}}]
        self.SimpleOVSDB.return_value = ovsdb
        self.assertTrue(self.target.configure_ovs_doca())
        ovsdb.open_vswitch.set.assert_called_once_with(
            '.', 'other_config:doca-init', 'true')

    def test_configure_ovs_datapath(self):
        self.patch_target('ovs_datapath_types', return_value={'doca'})
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [
            {'external_ids': {}, 'other_config': {}}]
        self.SimpleOVSDB.return_value = ovsdb
        self.assertTrue(self.target.configure_ovs_datapath())
        ovsdb.open_vswitch.set.assert_has_calls([
            mock.call('.', 'external_ids:ovn-bridge-datapath-type', 'doca'),
            mock.call('.', 'other_config:default-datapath-type', 'doca'),
        ], any_order=True)

    def test_datapath_type_pending(self):
        self.patch_target('ovs_datapath_types', return_value={'doca'})
        self.patch_target('charm_managed_bridges', return_value=[
            {'name': 'br-int', 'datapath_type': 'system'}])
        self.assertTrue(self.target.datapath_type_pending())

    def test_datapath_type_pending_in_sync(self):
        self.patch_target('ovs_datapath_types', return_value={'doca'})
        self.patch_target('charm_managed_bridges', return_value=[
            {'name': 'br-int', 'datapath_type': 'doca'}])
        self.assertFalse(self.target.datapath_type_pending())

    def test_custom_assess_status_last_check_pending(self):
        # The datapath became available on the reboot, and no hook has run
        # to move Open vSwitch onto it yet.
        self.patch_datapath_types(['system', 'doca'])
        self.patch_object(ovn_charm.ch_core.host, 'service_running',
                          return_value=True)
        self.patch_target('hugepages_reserved', return_value={1048576: 16})
        self.patch_target('datapath_type_pending', return_value=True)
        status, message = self.target.custom_assess_status_last_check()
        self.assertEqual(status, 'blocked')
        self.assertIn('resume', message)

    def test_configure_doca_source(self):
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=False)
        self.patch_object(ovn_charm.ch_fetch, 'filter_installed_packages',
                          return_value=['doca-host'])
        self.patch_object(ovn_charm.ch_fetch, 'apt_update')
        self.patch_target('run')
        self.target.configure_doca_source()
        self.run.assert_has_calls([
            mock.call('wget', '-O', '/tmp/doca-host.deb',
                      'https://example.com/doca-host.deb'),
            mock.call('dpkg', '-i', '/tmp/doca-host.deb'),
        ])
        self.apt_update.assert_called_once_with(fatal=True)

    def test_configure_doca_source_once_per_hook(self):
        # More than one handler may ask for an install in the same hook.
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.patch_object(ovn_charm.ch_fetch, 'filter_installed_packages',
                          return_value=['doca-host'])
        self.patch_object(ovn_charm.ch_fetch, 'apt_update')
        self.patch_target('run')
        self.target.configure_doca_source()
        self.target.configure_doca_source()
        self.apt_update.assert_called_once_with(fatal=True)

    def test_configure_doca_source_without_url(self):
        # The operator installed the host repository package themselves, so
        # the archive is not ours to configure.
        ovn_charm.ch_core.hookenv.config()['doca-url'] = ''
        self.target = ovn_charm.BaseOVNChassisCharm()
        self.patch_target('run')
        self.target.configure_doca_source()
        self.run.assert_not_called()

    def test_doca_packages_available(self):
        self.patch_object(ovn_charm.ch_fetch, 'apt_cache')
        self.assertTrue(self.target.doca_packages_available())
        self.apt_cache.return_value.__getitem__.side_effect = KeyError
        self.assertFalse(self.target.doca_packages_available())

    def test_custom_assess_status_last_check_archive_unconfigured(self):
        ovn_charm.ch_core.hookenv.config()['doca-url'] = ''
        self.target = ovn_charm.BaseOVNChassisCharm()
        self.patch_target('doca_packages_available', return_value=False)
        status, message = self.target.custom_assess_status_last_check()
        self.assertEqual(status, 'blocked')
        self.assertIn('doca-url', message)

    def test_custom_assess_status_last_check_archive_managed_by_operator(
            self):
        ovn_charm.ch_core.hookenv.config()['doca-url'] = ''
        self.target = ovn_charm.BaseOVNChassisCharm()
        self.patch_target('doca_packages_available', return_value=True)
        self.patch_object(ovn_charm.ch_core.host, 'service_running',
                          return_value=False)
        self.assertEqual(self.target.custom_assess_status_last_check(),
                         (None, None))

    def test_doca_packages_changing(self):
        self.patch_object(ovn_charm.ch_fetch, 'filter_installed_packages',
                          return_value=['doca-networking'])
        self.assertTrue(self.target.doca_packages_changing())
        self.filter_installed_packages.return_value = []
        self.assertFalse(self.target.doca_packages_changing())

    def test_configure_doca_source_already_configured(self):
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=False)
        self.patch_object(ovn_charm.ch_fetch, 'filter_installed_packages',
                          return_value=[])
        self.patch_object(ovn_charm.ch_fetch, 'apt_update')
        self.patch_target('run')
        self.target.configure_doca_source()
        self.run.assert_not_called()
        self.apt_update.assert_not_called()

    def test_configure_doca_source_url_changed(self):
        # A new archive has to be configured even though the package that
        # configures the previous one is installed.
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.patch_object(ovn_charm.ch_fetch, 'filter_installed_packages',
                          return_value=[])
        self.patch_object(ovn_charm.ch_fetch, 'apt_update')
        self.patch_target('run')
        self.target.configure_doca_source()
        self.assertTrue(self.run.called)

    def test_configure_ovs_restarts_for_doca_init(self):
        # ``doca-init`` is only read when ovs-vswitchd starts, and the
        # datapath type is resolved from what the running daemon offers.
        self.patch_target('run')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_key')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_cert')
        self.patch_object(ovn_charm.OVNConfigurationAdapter, 'ovn_ca_cert')
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        self.patch_object(ovn_charm.ch_core.host, 'service_start')
        self.patch_target('get_data_ip')
        self.patch_target('get_ovs_hostname')
        self.patch_target('check_if_paused', return_value=(None, None))
        self.patch_target('configure_ovs_doca', return_value=True)
        self.patch_target('configure_ovs_datapath')
        self.patch_target('configure_ovs_hw_offload', return_value=False)
        self.patch_target('configure_ovs_dpdk', return_value=False)
        self.target.configure_ovs('fake-sb-conn-str', False)
        self.service_restart.assert_called_once_with('openvswitch-switch')
        # The datapath defaults must be seeded before ovn-remote is set, as
        # that is what makes ovn-controller start creating resources.
        self.configure_ovs_datapath.assert_called_once_with()

    def test_configure_bridges(self):
        self.patch_target('ovs_datapath_types', return_value={'doca'})
        self.patch_object(ovn_charm, 'deferred_events')
        self.patch_object(ovn_charm.os_context, 'BridgePortInterfaceMap')
        dict_bpi = {
            'br-data': {        # bridge
                'bond0': {      # port
                                # interface(s) with interface data
                    'bond0': {'mtu-request': 9000},
                },
            },
        }
        mock_bpi = mock.MagicMock()
        mock_bpi.items.return_value = dict_bpi.items()
        mock_bpi.__iter__.side_effect = lambda: iter(dict_bpi)
        mock_bpi.__contains__.side_effect = dict_bpi.__contains__
        mock_bpi.__getitem__.side_effect = lambda x: dict_bpi.__getitem__(x)
        mock_bpi.get_ifdatamap.side_effect = lambda x, y: {
            k: v for k, v in dict_bpi[x][y].items()}
        self.BridgePortInterfaceMap.return_value = mock_bpi
        self.patch_object(ovn_charm.os_context, 'BondConfig')
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.port.find.return_value = []
        self.SimpleOVSDB.return_value = ovsdb
        self.patch_target('charm_managed_bridges', return_value=[
            {'name': 'br-int', 'datapath_type': 'system'}])
        self.patch_object(ovn_charm.ch_ovs, 'add_bridge')
        self.patch_object(ovn_charm.ch_ovs, 'add_bridge_port')
        self.patch_target('check_if_paused', return_value=(None, None))
        self.target.configure_bridges()
        self.add_bridge.assert_has_calls([
            mock.call(
                'br-int',
                brdata={
                    'external-ids': {'charm-ovn-chassis': 'managed'},
                    'datapath-type': 'doca',
                    'protocols': 'OpenFlow13,OpenFlow15',
                    'fail-mode': 'secure',
                    'other-config': {'disable-in-band': 'true'},
                }),
            mock.call(
                'br-data',
                brdata={
                    'external-ids': {'charm-ovn-chassis': 'managed'},
                    'datapath-type': 'doca',
                    'protocols': 'OpenFlow13,OpenFlow15',
                    'fail-mode': 'standalone',
                }),
        ], any_order=True)
        self.add_bridge_port.assert_called_once_with(
            'br-data', 'bond0', ifdata={
                'mtu-request': 9000,
                'type': 'doca',
                'options': {'dpdk-lsc-interrupt': 'true'},
                'external-ids': {'charm-ovn-chassis': 'br-data'}},
            linkup=True, promisc=None, portdata={
                'external-ids': {'charm-ovn-chassis': 'br-data'}})
        # The integration bridge was on another datapath, which
        # ovs-vswitchd only picks up when it reconfigures from scratch.
        ovn_charm.deferred_events.deferrable_svc_restart \
            .assert_called_once_with(
                'ovs-vswitchd', reason='datapath type changed')

    def patch_configure_bridges_bond0(self):
        """Map ``bond0`` on ``br-data`` on the ``doca`` datapath.

        :returns: The mocked ``SimpleOVSDB`` instance.
        :rtype: mock.MagicMock
        """
        self.patch_target('ovs_datapath_types', return_value={'doca'})
        self.patch_object(ovn_charm, 'deferred_events')
        self.patch_object(ovn_charm.os_context, 'BridgePortInterfaceMap')
        dict_bpi = {'br-data': {'bond0': {'bond0': {}}}}
        mock_bpi = mock.MagicMock()
        mock_bpi.items.return_value = dict_bpi.items()
        mock_bpi.__iter__.side_effect = lambda: iter(dict_bpi)
        mock_bpi.__contains__.side_effect = dict_bpi.__contains__
        mock_bpi.__getitem__.side_effect = lambda x: dict_bpi.__getitem__(x)
        mock_bpi.get_ifdatamap.side_effect = lambda x, y: {
            k: v for k, v in dict_bpi[x][y].items()}
        self.BridgePortInterfaceMap.return_value = mock_bpi
        self.patch_object(ovn_charm.os_context, 'BondConfig')
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.port.find.return_value = []
        ovsdb.interface.find.return_value = []
        self.SimpleOVSDB.return_value = ovsdb
        self.patch_target('charm_managed_bridges', return_value=[
            {'name': 'br-int', 'datapath_type': 'doca'}])
        self.patch_object(ovn_charm.ch_ovs, 'add_bridge')
        self.patch_object(ovn_charm.ch_ovs, 'add_bridge_port')
        self.patch_target('check_if_paused', return_value=(None, None))
        return ovsdb

    def test_pmd_cpu_mask(self):
        self.patch_target('ovs_datapath_types', return_value={'doca'})
        dpdk_context = mock.MagicMock()
        dpdk_context.pmd_cpu_mask.return_value = '0xf00'
        self.patch_object(ovn_charm.os_context, 'OVSDPDKDeviceContext',
                          return_value=dpdk_context)
        self.target.options.pmd_cpu_set = '8-11'
        self.assertEqual(self.target.pmd_cpu_mask(), '0xf00')

    def test_configure_ovs_dpdk_pmd_cpu_mask(self):
        # The doca datapath runs PMD threads in userspace like DPDK does,
        # even though enable-dpdk is not set.
        self.patch_target('pmd_cpu_mask', return_value='0xf00')
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{'other_config': {}}]
        self.SimpleOVSDB.return_value = ovsdb
        self.assertTrue(self.target.configure_ovs_dpdk())
        ovsdb.open_vswitch.set.assert_called_once_with(
            '.', 'other_config:pmd-cpu-mask', '0xf00')

    def test_configure_bridges_n_rxq(self):
        # One receive queue per PMD thread, so every PMD core polls the
        # uplink.  Taken from the mask Open vSwitch was given, which the
        # deferred configure_ovs may not have changed yet.
        ovsdb = self.patch_configure_bridges_bond0()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {'pmd-cpu-mask': '0xf00'}}]
        self.patch_target('pmd_cpu_mask')
        self.target.configure_bridges()
        self.pmd_cpu_mask.assert_not_called()
        self.add_bridge_port.assert_called_once_with(
            'br-data', 'bond0', ifdata={
                'type': 'doca',
                'options': {'dpdk-lsc-interrupt': 'true', 'n_rxq': '4'},
                'external-ids': {'charm-ovn-chassis': 'br-data'}},
            linkup=True, promisc=None, portdata={
                'external-ids': {'charm-ovn-chassis': 'br-data'}})

    def test_configure_bridges_n_rxq_unset(self):
        # ``pmd-cpu-set`` unset: the interface carries no ``n_rxq`` already,
        # so there is nothing to remove.
        ovsdb = self.patch_configure_bridges_bond0()
        ovsdb.open_vswitch.__iter__.return_value = [{'other_config': {}}]
        self.target.configure_bridges()
        self.add_bridge_port.assert_called_once_with(
            'br-data', 'bond0', ifdata={
                'type': 'doca',
                'options': {'dpdk-lsc-interrupt': 'true'},
                'external-ids': {'charm-ovn-chassis': 'br-data'}},
            linkup=True, promisc=None, portdata={
                'external-ids': {'charm-ovn-chassis': 'br-data'}})
        ovsdb.interface.remove.assert_not_called()

    def test_configure_bridges_n_rxq_removed(self):
        # ``pmd-cpu-set`` unset after having been set: the stale ``n_rxq``
        # is pruned, since ``add_bridge_port`` only ever adds options.
        ovsdb = self.patch_configure_bridges_bond0()
        ovsdb.interface.find.return_value = [
            {'name': 'bond0', 'options': {'n_rxq': '4'}}]
        self.patch_target('pmd_cpu_mask', return_value=None)
        self.target.configure_bridges()
        self.add_bridge_port.assert_called_once_with(
            'br-data', 'bond0', ifdata={
                'type': 'doca',
                'options': {'dpdk-lsc-interrupt': 'true'},
                'external-ids': {'charm-ovn-chassis': 'br-data'}},
            linkup=True, promisc=None, portdata={
                'external-ids': {'charm-ovn-chassis': 'br-data'}})
        ovsdb.interface.remove.assert_called_once_with(
            'bond0', 'options', 'n_rxq')

    def test_configure_bridges_leaves_epa_alone(self):
        # With restarts deferred, configure_ovs leaves the PMD threads
        # where they are, so the CPUs held for them must stay held too.
        self.patch_sysfs()
        ovsdb = self.patch_configure_bridges_bond0()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {'pmd-cpu-mask': '0xf00'}}]
        self.epa_available.return_value = True
        self.patch_object(ovn_charm.epa_client, 'allocate_numa_cores')
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.target.configure_bridges()
        self.allocate_numa_cores.assert_not_called()

    def test_configure_bridges_after_numa_discovery(self):
        # The CPU pinning in configure_ovs reads the bridge interface map
        # before configure_bridges does, on the same charm instance.
        self.patch_sysfs()
        self.add_netdev('eth0', numa_node=1)
        self.add_netdev('bond0', lower=('eth0',))
        ovsdb = self.patch_configure_bridges_bond0()
        ovsdb.open_vswitch.__iter__.return_value = [{'other_config': {}}]
        self.assertEqual(self.target.ovs_numa_nodes(), [1])
        self.assertEqual(self.target.ovs_numa_nodes(), [1])
        self.target.configure_bridges()
        self.add_bridge_port.assert_called_once()

    def test_configure_bridges_no_restart_when_in_sync(self):
        self.patch_target('ovs_datapath_types', return_value={'doca'})
        self.patch_object(ovn_charm, 'deferred_events')
        self.patch_object(ovn_charm.os_context, 'BridgePortInterfaceMap')
        self.BridgePortInterfaceMap.return_value = {}
        self.patch_object(ovn_charm.os_context, 'BondConfig')
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        self.patch_target('charm_managed_bridges', return_value=[
            {'name': 'br-int', 'datapath_type': 'doca'}])
        self.patch_object(ovn_charm.ch_ovs, 'add_bridge')
        self.patch_target('check_if_paused', return_value=(None, None))
        self.target.configure_bridges()
        self.assertFalse(
            ovn_charm.deferred_events.deferrable_svc_restart.called)

    def patch_install(self):
        self.patch_object(ovn_charm.reactive, 'set_flag')
        self.patch_object(ovn_charm.ch_core.host, 'service_stop')
        self.patch_object(ovn_charm.ch_core.host, 'service_start')
        self.patch_object(ovn_charm.ch_core.host, 'service_restart')
        self.patch_target('configure_sources')
        self.patch_target('render_configs')
        self.patch_target('remove_obsolete_packages', return_value=False)
        self.patch_target('run')
        self.patch_target('update_api_ports')

    def test_install_stops_ovn_controller_on_transition(self):
        # The DOCA packages replace the ones providing Open vSwitch, which
        # ovn-controller must not reconcile against while it happens.
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.patch_object(ovn_charm.ch_fetch, 'filter_installed_packages',
                          return_value=['doca-networking'])
        self.patch_install()
        self.target.install()
        self.service_stop.assert_called_once_with('ovn-controller')
        self.service_start.assert_called_once_with('ovn-controller')

    def test_install_leaves_installed_packages_alone(self):
        # Nothing is replaced underneath ovn-controller when the packages
        # are already in place.
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=True)
        self.patch_object(ovn_charm.ch_fetch, 'filter_installed_packages',
                          return_value=[])
        self.patch_install()
        self.target.install()
        self.assertNotIn(mock.call('ovn-controller'),
                         self.service_stop.mock_calls)

    def test_install_records_ownership(self):
        # Which is what tells the packages apart from an installation
        # performed by the host's image.
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=False)
        self.patch_object(ovn_charm.ch_fetch, 'filter_installed_packages',
                          return_value=['doca-networking'])
        self.patch_install()
        self.target.install()
        self.set_flag.assert_called_once_with('charm.ovn.doca-managed')

    def test_install_leaves_provisioned_packages_alone(self):
        # LP: #2170179.  The packages were there before the charm arrived,
        # so they are not ours to claim, and nothing is replaced underneath
        # ovn-controller.
        self.patch_object(ovn_charm.reactive, 'is_flag_set',
                          return_value=False)
        self.patch_object(ovn_charm.ch_fetch, 'filter_installed_packages',
                          return_value=[])
        self.patch_install()
        self.target.install()
        self.set_flag.assert_not_called()
        self.assertNotIn(mock.call('ovn-controller'),
                         self.service_stop.mock_calls)


class TestHWOffloadChassisCharm(Helper):

    def setUp(self):
        super().setUp(config={
            'enable-hardware-offload': True,
            'enable-sriov': False,
            'enable-dpdk': False,
            'install-doca': False,
            'enable-doca': False,
            'bridge-interface-mappings': 'br-ex:eth0',
            'ovn-bridge-mappings': 'physnet2:br-ex',
            'ovn-source': 'distro',
        })

    def test__init__(self):
        self.assertEqual(self.target.packages, [
            'ovn-host',
        ])
        self.assertDictEqual(self.target.restart_map, {
            '/etc/netplan/150-charm-ovn.yaml': [],
            '/etc/default/openvswitch-switch': [],
            '/etc/openvswitch/system-id.conf': [],
        })
        self.assertEqual(self.target.group, 'root')

    def test_install(self):
        self.patch_target('configure_source')
        self.patch_target('run')
        self.patch_target('update_api_ports')
        self.target.install()

    def test_configure_ovs_hw_offload(self):
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {
                'hw-offload': 'true',
                'max-idle': '30000',
                'hw-offload-ct-ipv6-enabled': 'true',
            },
        }]
        self.SimpleOVSDB.return_value = ovsdb
        self.assertFalse(self.target.configure_ovs_hw_offload())
        ovsdb.open_vswitch.set.assert_not_called()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {
                'hw-offload': 'false',
                'max-idle': '30000',
                'hw-offload-ct-ipv6-enabled': 'true',
            },
        }]
        self.assertTrue(self.target.configure_ovs_hw_offload())
        ovsdb.open_vswitch.set.assert_called_once_with(
            '.', 'other_config:hw-offload', 'true')
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {
                'hw-offload': 'true',
                'max-idle': '42',
                'hw-offload-ct-ipv6-enabled': 'true',
            },
        }]
        ovsdb.open_vswitch.set.reset_mock()
        self.assertTrue(self.target.configure_ovs_hw_offload())
        ovsdb.open_vswitch.set.assert_called_once_with(
            '.', 'other_config:max-idle', '30000')

    def test_configure_ovs_hw_offload_ct_ipv6(self):
        # Offloading connection tracking of IPv6 flows is disabled by
        # default in OVS-DOCA.
        self.patch_object(ovn_charm.ch_ovsdb, 'SimpleOVSDB')
        ovsdb = mock.MagicMock()
        ovsdb.open_vswitch.__iter__.return_value = [{
            'other_config': {
                'hw-offload': 'true',
                'max-idle': '30000',
            },
        }]
        self.SimpleOVSDB.return_value = ovsdb
        self.assertTrue(self.target.configure_ovs_hw_offload())
        ovsdb.open_vswitch.set.assert_called_once_with(
            '.', 'other_config:hw-offload-ct-ipv6-enabled', 'true')
