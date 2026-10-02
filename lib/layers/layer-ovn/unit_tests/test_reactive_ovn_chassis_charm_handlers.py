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

import io
import mock

from pathlib import Path

import reactive.ovn_chassis_charm_handlers as handlers

import charms_openstack.test_utils as test_utils


class TestRegisteredHooks(test_utils.TestRegisteredHooks):

    def test_hooks(self):
        defaults = [
            'config.changed',
            'config.rendered',
            'charm.default-select-release',
            'update-status',
            'upgrade-charm',
            'certificates.available',
        ]
        hook_set = {
            'when': {
                'amqp_connection': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'amqp.connected',),
                'enable_chassis_reactive_code': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'charm.installed'),
                'configure_ovs': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'ovsdb.available',
                    'certificates.available'),
                'disable_openstack': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,),
                'enable_openstack': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'nova-compute.connected',),
                'pause_unit_from_config': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'config.set.new-units-paused'),
                'configure_nrpe': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'config.rendered',),
                'provide_chassis_certificates_to_principal': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'ovsdb-subordinate.available',
                    'ovn.certs.changed'),
                'stamp_fresh_deployment': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'leadership.is_leader'),
                'stamp_upgraded_deployment': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'charm.installed',
                    'leadership.is_leader'),
                'enable_install': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,),
                'handle_metrics_endpoint': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'charm.installed',
                    'metrics-endpoint.available',
                    'snap.installed.prometheus-ovs-exporter',
                ),
                'reassess_exporter': (
                    'charm.installed',
                ),
                'maybe_clear_metrics_endpoint': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'charm.installed',
                    'metrics-endpoint.available',
                ),
                'configure_cos_agent': (
                    handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG,
                    'cos-agent.available',
                    'snap.installed.prometheus-ovs-exporter',
                ),
            },
            'when_not': {
                'snap_install': (
                    'snap.installed.prometheus-ovs-exporter',
                ),
                'maybe_clear_metrics_endpoint': (
                    'snap.installed.prometheus-ovs-exporter',
                ),
            },
            'when_none': {
                'amqp_connection': ('charm.paused', 'is-update-status-hook'),
                'disable_openstack': (
                    'charm.paused',
                    'is-update-status-hook',
                    'nova-compute.connected',),
                'enable_openstack': ('charm.paused', 'is-update-status-hook'),
                'configure_ovs': ('charm.paused', 'is-update-status-hook'),
                'pause_unit_from_config': ('charm.installed', 'charm.paused'),
                'configure_nrpe': (
                    'charm.paused',
                    'is-update-status-hook',),
                'provide_chassis_certificates_to_principal': (
                    'charm.paused',
                    'is-update-status-hook',),
                'stamp_fresh_deployment': (
                    'charm.installed', 'leadership.set.install_stamp'),
                'stamp_upgraded_deployment': (
                    'is-update-status-hook',
                    'leadership.set.install_stamp',
                    'leadership.set.upgrade_stamp'),
                'enable_install': (
                    'charm.installed', 'is-update-status-hook'),
                'reassess_exporter': (
                    'is-update-status-hook',),
                'maybe_clear_metrics_endpoint': (
                    'is-update-status-hook',),
                'handle_metrics_endpoint': (
                    'is-update-status-hook',),
                'configure_cos_agent': ('is-update-status-hook',),
            },
            'when_any': {
                'configure_bridges': (
                    'config.changed.ovn-bridge-mappings',
                    'config.changed.bridge-interface-mappings',
                    'run-default-upgrade-charm',),
                'configure_nrpe': (
                    'config.changed.nagios_context',
                    'config.changed.nagios_servicegroups',
                    'endpoint.nrpe-external-master.changed',
                    'nrpe-external-master.available'),
                'enable_install': (
                    'leadership.set.install_stamp',
                    'leadership.set.upgrade_stamp'),
                'reassess_exporter': (
                    'config.changed.ovs-exporter-channel',
                    'snap.installed.prometheus-ovs-exporter'),
            },
        }
        # test that the hooks were registered via the
        # reactive.ovn_handlers
        handlers.enable_chassis_reactive_code()
        self.registered_hooks_test_helper(handlers, hook_set, defaults)


class TestOvnHandlers(test_utils.PatchHelper):

    def setUp(self):
        super().setUp()
        self.charm = mock.MagicMock()
        self.patch_object(handlers.charm, 'provide_charm_instance',
                          new=mock.MagicMock())
        self.provide_charm_instance().__enter__.return_value = \
            self.charm
        self.provide_charm_instance().__exit__.return_value = None

    def test_amqp_connection(self):
        self.patch_object(handlers.reactive, 'endpoint_from_flag')
        amqp = mock.MagicMock()
        self.endpoint_from_flag.return_value = amqp
        handlers.amqp_connection()
        amqp.request_access.assert_called_once_with(
            username='neutron', vhost='openstack')
        self.charm.assess_status.assert_called_once_with()

    def test_disable_openstack(self):
        self.patch_object(handlers.reactive, 'clear_flag')
        handlers.disable_openstack()
        self.clear_flag.assert_called_once_with(
            'charm.ovn-chassis.enable-openstack')

    def test_enable_openstack(self):
        self.patch_object(handlers.reactive, 'endpoint_from_flag')
        self.patch_object(handlers.reactive, 'set_flag')
        nova_compute = mock.MagicMock()
        self.endpoint_from_flag.return_value = nova_compute
        handlers.enable_openstack()
        self.set_flag.assert_called_once_with(
            'charm.ovn-chassis.enable-openstack')
        nova_compute.publish_shared_secret.assert_called_once_with()
        self.charm.install.assert_called_once_with()
        self.charm.assess_status.assert_called_once_with()

    def test_configure_ovs(self):
        self.patch_object(handlers.reactive, 'endpoint_from_flag')
        self.patch_object(handlers.charm, 'optional_interfaces')
        self.patch_object(handlers.reactive, 'set_flag')
        self.patch_object(handlers.reactive, 'is_flag_set', return_value=True)
        ovsdb = mock.MagicMock()
        ovsdb.db_sb_connection_strs = [
            'ssl:192.0.2.11:6642',
            'ssl:192.0.2.12:6642',
            'ssl:192.0.2.13:6642',
        ]
        self.endpoint_from_flag.return_value = ovsdb
        handlers.configure_ovs()
        self.charm.configure_ovs.assert_called_once_with(
            ','.join(ovsdb.db_sb_connection_strs), True)
        self.charm.render_with_interfaces.assert_called_once_with(
            self.optional_interfaces((ovsdb,),
                                     'nova-compute.connected',
                                     'amqp.connected'))
        self.set_flag.assert_called_once_with('config.rendered')
        self.charm.configure_bridges.assert_called_once_with()
        self.charm.configure_iptables_rules.assert_called_once_with()
        self.charm.assess_status.assert_called_once_with()

    def test_configure_ovs_no_sb_conn(self):
        self.patch_object(handlers.reactive, 'endpoint_from_flag')
        self.patch_object(handlers.charm, 'optional_interfaces')
        self.patch_object(handlers.reactive, 'set_flag')
        self.patch_object(handlers.reactive, 'is_flag_set', return_value=True)
        ovsdb = mock.MagicMock()
        ovsdb.db_sb_connection_strs = []
        self.endpoint_from_flag.return_value = ovsdb
        handlers.configure_ovs()
        self.charm.configure_ovs.assert_called_once_with(
            ','.join(ovsdb.db_sb_connection_strs), True)
        self.charm.render_with_interfaces.assert_called_once_with(
            self.optional_interfaces((ovsdb,),
                                     'nova-compute.connected',
                                     'amqp.connected'))
        self.set_flag.assert_called_once_with('config.rendered')
        self.charm.configure_bridges.assert_called_once_with()
        self.charm.configure_iptables_rules.assert_called_once_with()
        self.charm.assess_status.assert_called_once_with()

    def test_configure_nrpe(self):
        self.patch_object(handlers.reactive, 'endpoint_from_flag')
        self.endpoint_from_flag.return_value = 'nrpe-external-master'
        self.patch_object(handlers.charm, 'provide_charm_instance')
        handlers.configure_nrpe()
        self.provide_charm_instance.assert_has_calls([
            mock.call().__enter__().render_nrpe(),
        ])

    def test_reassess_exporter(self):
        self.patch_object(handlers.charm, 'provide_charm_instance')
        handlers.reassess_exporter()
        self.provide_charm_instance.assert_has_calls([
            mock.call().__enter__().assess_exporter(),
            mock.call().__enter__().restart_exporter(only_inactive=True),
        ])

    def test_pause_unit_from_config(self):
        handlers.pause_unit_from_config()
        self.charm.pause.assert_called_once_with()
        self.charm.assess_status.assert_called_once_with()

    def test_provide_chassis_certificates_to_principal(self):
        self.patch_object(handlers.reactive, 'endpoint_from_flag')
        ovsdb_subordinate = mock.MagicMock()
        self.endpoint_from_flag.return_value = ovsdb_subordinate
        with mock.patch('builtins.open', create=True) as mocked_open:
            mocked_file = mock.MagicMock(spec=io.FileIO)
            mocked_file.__enter__().read.return_value = 'fakecert'
            mocked_open.return_value = mocked_file
            handlers.provide_chassis_certificates_to_principal()
            self.endpoint_from_flag.assert_called_once_with(
                'ovsdb-subordinate.available')
            mocked_open.assert_has_calls([
                mock.call(self.charm.options.ovn_ca_cert, 'r'),
                mock.call(self.charm.options.ovn_cert, 'r'),
                mock.call(self.charm.options.ovn_key, 'r'),
            ], any_order=True)
            ovsdb_subordinate.publish_chassis_certificates.\
                assert_called_once_with('fakecert', 'fakecert', 'fakecert')

    def test_stamp_fresh_deployment(self):
        self.patch_object(handlers.leadership, 'leader_set')
        handlers.stamp_fresh_deployment()
        self.leader_set.assert_called_once_with(install_stamp=2203)

    def test_stamp_upgraded_deployment(self):
        self.patch_object(handlers.leadership, 'leader_set')
        handlers.stamp_upgraded_deployment()
        self.leader_set.assert_called_once_with(upgrade_stamp=2203)

    def test_enable_install(self):
        self.patch_object(handlers.charm, 'use_defaults')
        handlers.enable_install()
        self.use_defaults.assert_called_once_with('charm.installed')

    def test_configure_cos_agent_fresh(self):
        """Test that configuration is triggered if it wasn't done already."""
        self.patch_object(handlers.reactive, 'is_flag_set')
        self.is_flag_set.return_value = False

        self.patch_object(handlers.os, 'getenv')
        self.getenv.return_value = "/tmp/"

        self.patch_object(handlers.reactive, 'endpoint_from_flag')
        mock_endpoint = mock.MagicMock()
        mock_metrics_config = mock.MagicMock()
        mock_endpoint.MetricsEndpoint.return_value = mock_metrics_config
        self.endpoint_from_flag.return_value = mock_endpoint

        self.patch_object(handlers.ch_core.hookenv, 'hook_name')
        self.hook_name.return_value = 'foo'

        self.patch_object(handlers.reactive, 'set_flag')

        handlers.configure_cos_agent()

        mock_endpoint.MetricsEndpoint.assert_called_once_with(
            port=9475,
            dashboards_dir=Path("/tmp/").joinpath('files', 'dashboards'),
        )
        mock_endpoint.update_cos_agent.assert_called_once_with(
            [mock_metrics_config]
        )
        self.set_flag.assert_called_once_with('cos-agent.configured')

    def test_configure_cos_agent_force(self):
        """Test that cos_agent is always reconfigured on upgrade hook."""
        self.patch_object(handlers.reactive, 'is_flag_set')
        self.is_flag_set.return_value = True

        self.patch_object(handlers.os, 'getenv')
        self.getenv.return_value = "/tmp/"

        self.patch_object(handlers.reactive, 'endpoint_from_flag')
        mock_endpoint = mock.MagicMock()
        mock_metrics_config = mock.MagicMock()
        mock_endpoint.MetricsEndpoint.return_value = mock_metrics_config
        self.endpoint_from_flag.return_value = mock_endpoint

        self.patch_object(handlers.ch_core.hookenv, 'hook_name')
        self.hook_name.return_value = 'upgrade-charm'

        self.patch_object(handlers.reactive, 'set_flag')

        handlers.configure_cos_agent()

        mock_endpoint.MetricsEndpoint.assert_called_once_with(
            port=9475,
            dashboards_dir=Path("/tmp/").joinpath('files', 'dashboards'),
        )
        mock_endpoint.update_cos_agent.assert_called_once_with(
            [mock_metrics_config]
        )
        self.set_flag.assert_called_once_with('cos-agent.configured')

    def test_configure_cos_agent_skip(self):
        """Test that cos_agent is not reconfigured after initially set up."""
        self.patch_object(handlers.reactive, 'is_flag_set')
        self.is_flag_set.return_value = True

        self.patch_object(handlers.os, 'getenv')
        self.getenv.return_value = "/tmp/"

        self.patch_object(handlers.reactive, 'endpoint_from_flag')
        mock_endpoint = mock.MagicMock()
        self.endpoint_from_flag.return_value = mock_endpoint

        self.patch_object(handlers.ch_core.hookenv, 'hook_name')
        self.hook_name.return_value = 'foo'

        self.patch_object(handlers.reactive, 'set_flag')

        handlers.configure_cos_agent()

        mock_endpoint.update_cos_agent.assert_not_called()
        self.set_flag.assert_not_called()
