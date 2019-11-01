import mock
import subprocess

import charms_openstack.test_utils as test_utils

import charm.ovsdb as ovsdb

VSCTL_BRIDGE_TBL = '''
{"data":[[["uuid","1e21ba48-61ff-4b32-b35e-cb80411da351"],["set",[]],["set",[]],"0000a0369fdd3890","","<unknown>",["map",[["charm-ovn-chassis","managed"],["other","value"]]],["set",[]],["set",[]],["map",[]],["set",[]],false,["set",[]],"br-test",["set",[]],["map",[]],["set",[["uuid","617f9359-77e2-41be-8af6-4c44e7a6bcc3"],["uuid","da840476-8809-4107-8733-591f4696f056"]]],["set",[]],false,["map",[]],["set",[]],["map",[]],false],[["uuid","bb685b0f-a383-40a1-b7a5-b5c2066bfa42"],["set",[]],["set",[]],"00000e5b68bba140","","<unknown>",["map",[]],"secure",["set",[]],["map",[]],["set",[]],false,["set",[]],"br-int",["set",[]],["map",[["disable-in-band","true"]]],["set",[["uuid","07f4c231-9fd2-49b0-a558-5b69d657fdb0"],["uuid","8bbd2441-866f-4317-a284-09491702776c"],["uuid","d9e9c081-6482-4006-b7d6-239182b56c2e"]]],["set",[]],false,["map",[]],["set",[]],["map",[]],false]],"headings":["_uuid","auto_attach","controller","datapath_id","datapath_type","datapath_version","external_ids","fail_mode","flood_vlans","flow_tables","ipfix","mcast_snooping_enable","mirrors","name","netflow","other_config","ports","protocols","rstp_enable","rstp_status","sflow","status","stp_enable"]}
'''


class TestOVSDB(test_utils.PatchHelper):

    def test__run(self):
        self.patch_object(ovsdb.subprocess, 'run')
        self.run.return_value = 'aReturn'
        self.assertEquals(ovsdb._run('aArg'), 'aReturn')
        self.run.assert_called_once_with(
            ('aArg',), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=True, universal_newlines=True)

    def test_add_br(self):
        self.patch_object(ovsdb, '_run')
        ovsdb.add_br('br-x')
        self._run.assert_called_once_with(
            'ovs-vsctl', 'add-br', 'br-x', '--', 'set', 'bridge', 'br-x',
            'protocols=OpenFlow13')
        self._run.reset_mock()
        ovsdb.add_br('br-x', ('charm', 'managed'))
        self._run.assert_called_once_with(
            'ovs-vsctl', 'add-br', 'br-x', '--', 'set', 'bridge', 'br-x',
            'protocols=OpenFlow13', '--',
            'br-set-external-id', 'br-x', 'charm', 'managed')

    def test_del_br(self):
        self.patch_object(ovsdb, '_run')
        ovsdb.del_br('br-x')
        self._run.assert_called_once_with(
            'ovs-vsctl', 'del-br', 'br-x')

    def test_add_port(self):
        self.patch_object(ovsdb, '_run')
        ovsdb.add_port('br-x', 'enp3s0f0')
        self._run.assert_has_calls([
            mock.call('ip', 'link', 'set', 'enp3s0f0', 'up'),
            mock.call('ovs-vsctl', 'add-port', 'br-x', 'enp3s0f0'),
        ])

    def test_list_ports(self):
        self.patch_object(ovsdb, '_run')
        ovsdb.list_ports('someBridge')
        self._run.assert_called_once_with('ovs-vsctl', 'list-ports',
                                          'someBridge')


class Helper(test_utils.PatchHelper):

    def patch_target(self, attr, return_value=None):
        mocked = mock.patch.object(self.target, attr)
        self._patches[attr] = mocked
        started = mocked.start()
        started.return_value = return_value
        self._patches_start[attr] = started
        setattr(self, attr, started)


class TestSimpleOVSDB(Helper):

    def setUp(self):
        super().setUp()
        self.target = ovsdb.SimpleOVSDB('atool', 'atable')

    def test__find_tbl(self):
        self.patch_object(ovsdb, '_run')
        cp = mock.MagicMock()
        cp.stdout = mock.PropertyMock().return_value = VSCTL_BRIDGE_TBL
        self._run.return_value = cp
        self.maxDiff = None
        expect = {
            '_uuid': '1e21ba48-61ff-4b32-b35e-cb80411da351',
            'auto_attach': [],
            'controller': [],
            'datapath_id': '0000a0369fdd3890',
            'datapath_type': '',
            'datapath_version': '<unknown>',
            'external_ids': [['charm-ovn-chassis', 'managed'],
                             ['other', 'value']],
            'fail_mode': [],
            'flood_vlans': [],
            'flow_tables': [],
            'ipfix': [],
            'mcast_snooping_enable': False,
            'mirrors': [],
            'name': 'br-test',
            'netflow': [],
            'other_config': [],
            'ports': [['uuid', '617f9359-77e2-41be-8af6-4c44e7a6bcc3'],
                      ['uuid', 'da840476-8809-4107-8733-591f4696f056']],
            'protocols': [],
            'rstp_enable': False,
            'rstp_status': [],
            'sflow': [],
            'status': [],
            'stp_enable': False}
        # this in effect also tests the __iter__ front end method
        for el in self.target:
            self.assertDictEqual(el, expect)
            break
        self._run.assert_called_once_with(
            'atool', '-f', 'json', 'find', 'atable')
        self._run.reset_mock()
        # this in effect also tests the find front end method
        for el in self.target.find(condition='name=br-test'):
            break
        self._run.assert_called_once_with(
            'atool', '-f', 'json', 'find', 'atable', 'name=br-test')

    def test_clear(self):
        self.patch_object(ovsdb, '_run')
        self.target.clear('1e21ba48-61ff-4b32-b35e-cb80411da351',
                          'external_ids')
        self._run.assert_called_once_with(
            'atool', 'clear', 'atable',
            '1e21ba48-61ff-4b32-b35e-cb80411da351', 'external_ids')

    def test_remove(self):
        self.patch_object(ovsdb, '_run')
        self.target.remove('1e21ba48-61ff-4b32-b35e-cb80411da351',
                           'external_ids', 'other')
        self._run.assert_called_once_with(
            'atool', 'remove', 'atable',
            '1e21ba48-61ff-4b32-b35e-cb80411da351', 'external_ids', 'other')

    def test_set(self):
        self.patch_object(ovsdb, '_run')
        self.target.set('1e21ba48-61ff-4b32-b35e-cb80411da351',
                        'external_ids:other', 'value')
        self._run.assert_called_once_with(
            'atool', 'set', 'atable',
            '1e21ba48-61ff-4b32-b35e-cb80411da351', 'external_ids:other=value')
