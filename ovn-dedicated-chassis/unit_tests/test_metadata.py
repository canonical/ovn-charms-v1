# Copyright 2026 Canonical Ltd
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

import base64
import configparser
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import jinja2
import yaml
import charms_openstack.test_utils as test_utils


SOURCE = Path(__file__).resolve().parents[1] / 'src'
METADATA = yaml.safe_load((SOURCE / 'metadata.yaml').read_text())
INTERFACE = METADATA['provides']['nova-compute']['interface']
spec = importlib.util.spec_from_file_location(
    'metadata_provider',
    SOURCE / 'hooks/relations' / INTERFACE / 'provides.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)


class TestMetadataRelation(test_utils.PatchHelper):

    def setUp(self):
        super().setUp()
        self.patch_object(provider, 'toggle_flag')
        self.endpoint = provider.NeutronPluginRemoteProvides()
        self.endpoint.expand_name = lambda flag: flag.replace(
            '{endpoint_name}', 'nova-compute')
        self.endpoint.all_joined_units = []
        self.endpoint.relations = [SimpleNamespace(to_publish_raw={})]

    @staticmethod
    def unit(address, secret=None):
        return SimpleNamespace(received_raw={
            'private-address': address, 'metadata-shared-secret': secret})

    def test_dpu_added_after_local_provider_adopts_existing_secret(self):
        compute = self.unit('192.0.2.10', 'existing-local-secret')
        self.endpoint.all_joined_units = [compute]
        self.endpoint.manage_flags()
        self.toggle_flag.assert_called_once_with(
            'nova-compute.connected', True)
        self.assertEqual(('192.0.2.10', 'existing-local-secret'),
                         self.endpoint.metadata_endpoint)
        self.endpoint.publish_shared_secret()
        self.assertEqual({}, self.endpoint.relations[0].to_publish_raw)
        self.assertEqual('existing-local-secret',
                         compute.received_raw['metadata-shared-secret'])

    def test_waits_for_local_provider_and_adopts_late_credentials(self):
        compute = self.unit('192.0.2.10')
        self.endpoint.all_joined_units = [compute]
        self.endpoint.manage_flags()
        self.toggle_flag.assert_called_with('nova-compute.connected', False)
        self.assertIsNone(self.endpoint.get_or_create_shared_secret())
        self.assertEqual({}, self.endpoint.relations[0].to_publish_raw)
        compute.received_raw['metadata-shared-secret'] = 'local-secret'
        self.endpoint.manage_flags()
        self.toggle_flag.assert_called_with('nova-compute.connected', True)
        self.assertEqual('local-secret',
                         self.endpoint.get_or_create_shared_secret())

    def test_no_complete_endpoint_does_not_enable_metadata(self):
        for units in ([], [self.unit(None, 'secret')],
                      [self.unit('192.0.2.10')],
                      [self.unit('192.0.2.10', '')],
                      [self.unit('192.0.2.10', ' ')]):
            with self.subTest(units=units):
                self.endpoint.all_joined_units = units
                self.endpoint.manage_flags()
                self.toggle_flag.assert_called_with('nova-compute.connected',
                                                    False)
                self.assertEqual((None, None), self.endpoint.metadata_endpoint)

    def test_does_not_combine_incomplete_advertisements(self):
        self.endpoint.all_joined_units = [
            self.unit('192.0.2.10'), self.unit(None, 'other-compute-secret')]
        self.assertEqual((None, None), self.endpoint.metadata_endpoint)

    def test_skips_incomplete_unit_for_complete_pair(self):
        self.endpoint.all_joined_units = [
            self.unit('192.0.2.10'), self.unit('192.0.2.11', 'secret-1')]
        self.assertEqual(('192.0.2.11', 'secret-1'),
                         self.endpoint.metadata_endpoint)

    def test_different_compute_secrets_switch_with_address_on_departure(self):
        self.endpoint.all_joined_units = [
            self.unit('192.0.2.10', 'secret-0'),
            self.unit('192.0.2.11', 'secret-1')]
        self.assertEqual('192.0.2.10', self.endpoint.metadata_host)
        self.assertEqual('secret-0',
                         self.endpoint.get_or_create_shared_secret())
        self.endpoint.all_joined_units.pop(0)
        self.assertEqual('192.0.2.11', self.endpoint.metadata_host)
        self.assertEqual('secret-1',
                         self.endpoint.get_or_create_shared_secret())

    def test_withdrawal_selects_another_complete_pair(self):
        first = self.unit('192.0.2.10', 'secret-0')
        second = self.unit('192.0.2.11', 'secret-1')
        self.endpoint.all_joined_units = [first, second]
        first.received_raw['metadata-shared-secret'] = ''
        self.endpoint.manage_flags()
        self.toggle_flag.assert_called_with('nova-compute.connected', True)
        self.assertEqual(('192.0.2.11', 'secret-1'),
                         self.endpoint.metadata_endpoint)
        second.received_raw['metadata-shared-secret'] = ''
        self.endpoint.manage_flags()
        self.toggle_flag.assert_called_with('nova-compute.connected', False)

    def test_secret_rotation_is_read_from_selected_compute(self):
        compute = self.unit('192.0.2.10', 'old-local-secret')
        self.endpoint.all_joined_units = [compute]
        self.assertEqual('old-local-secret',
                         self.endpoint.get_or_create_shared_secret())
        compute.received_raw['metadata-shared-secret'] = 'new-local-secret'
        self.assertEqual(('192.0.2.10', 'new-local-secret'),
                         self.endpoint.metadata_endpoint)

    def test_upgrade_withdraws_old_dpu_secrets_before_nova_is_ready(self):
        self.endpoint.relations = [SimpleNamespace(to_publish_raw={
            'metadata-shared-secret': 'old-dpu-secret', 'other': 'keep'}),
            SimpleNamespace(to_publish_raw={'metadata-shared-secret': 'old'})]
        self.endpoint.manage_flags()
        self.toggle_flag.assert_called_with('nova-compute.connected', False)
        for relation in self.endpoint.relations:
            self.assertIsNone(
                relation.to_publish_raw['metadata-shared-secret'])
        self.assertEqual('keep', self.endpoint.relations[0].to_publish_raw[
            'other'])
        self.endpoint.all_joined_units = [self.unit('192.0.2.10', 'local')]
        self.endpoint.publish_shared_secret()
        for relation in self.endpoint.relations:
            self.assertIsNone(
                relation.to_publish_raw['metadata-shared-secret'])

    def test_controller_transport_settings_follow_selected_unit(self):
        first = self.unit('metadata.example.test', 'controller-secret')
        first.received_raw.update({
            'nova-metadata-protocol': 'https',
            'nova-metadata-port': '18775',
            'ca_cert': base64.b64encode(b'controller-ca').decode(),
        })
        second = self.unit('192.0.2.11', 'other-secret')
        self.endpoint.all_joined_units = [first, second]
        self.assertEqual('https', self.endpoint.metadata_protocol)
        self.assertEqual(18775, self.endpoint.metadata_port)
        self.assertEqual('controller-ca', self.endpoint.metadata_ca_cert)
        self.endpoint.all_joined_units.pop(0)
        self.assertEqual('http', self.endpoint.metadata_protocol)
        self.assertEqual(8775, self.endpoint.metadata_port)
        self.assertEqual('', self.endpoint.metadata_ca_cert)
        self.assertEqual('other-secret',
                         self.endpoint.get_or_create_shared_secret())

    def test_rejects_invalid_transport_settings(self):
        for settings in ({'nova-metadata-protocol': 'ftp'},
                         {'nova-metadata-port': 'invalid'},
                         {'nova-metadata-port': 0},
                         {'nova-metadata-port': 65536}):
            with self.subTest(settings=settings):
                unit = self.unit('192.0.2.10', 'secret')
                unit.received_raw.update(settings)
                self.endpoint.all_joined_units = [unit]
                self.endpoint.manage_flags()
                self.toggle_flag.assert_called_with(
                    'nova-compute.connected', False)

    def test_malformed_ca_is_not_silently_ignored(self):
        unit = self.unit('192.0.2.10', 'secret')
        unit.received_raw['ca_cert'] = 'not-base64!'
        self.endpoint.all_joined_units = [unit]
        with self.assertRaises(ValueError):
            self.endpoint.metadata_ca_cert


class TestMetadataConfiguration(test_utils.PatchHelper):

    def test_renders_remote_api_and_ovn_connections(self):
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(SOURCE / 'templates'),
            undefined=jinja2.StrictUndefined)
        template = env.get_template('neutron_ovn_metadata_agent.ini')
        for address in ('192.0.2.10', '2001:db8::10'):
            with self.subTest(address=address):
                config = configparser.ConfigParser()
                config.read_string(template.render(
                    options=SimpleNamespace(
                        debug=False,
                        ovn_key='/etc/ovn/key_host',
                        ovn_cert='/etc/ovn/cert_host',
                        ovn_ca_cert='/etc/ovn/ovn-dedicated-chassis.crt'),
                    nova_compute=SimpleNamespace(
                        metadata_host=address,
                        metadata_protocol='https',
                        metadata_port=18775,
                        metadata_ca_cert='controller-ca',
                        metadata_shared_secret='shared-secret'),
                    ovsdb=SimpleNamespace(db_sb_connection_strs=[
                        'ssl:192.0.2.20:6642', 'ssl:192.0.2.21:6642'])))
                self.assertEqual(address,
                                 config['DEFAULT']['nova_metadata_host'])
                self.assertEqual('shared-secret', config['DEFAULT'][
                    'metadata_proxy_shared_secret'])
                self.assertEqual('https', config['DEFAULT'][
                    'nova_metadata_protocol'])
                self.assertEqual('18775', config['DEFAULT'][
                    'nova_metadata_port'])
                self.assertEqual('false', config['DEFAULT'][
                    'nova_metadata_insecure'])
                self.assertEqual('/etc/neutron/nova-metadata-ca.crt',
                                 config['DEFAULT']['auth_ca_cert'])
                self.assertEqual('tcp:127.0.0.1:6640',
                                 config['ovs']['ovsdb_connection'])
                self.assertEqual(
                    'ssl:192.0.2.20:6642,ssl:192.0.2.21:6642',
                    config['ovn']['ovn_sb_connection'])
                self.assertEqual('/etc/ovn/key_host',
                                 config['ovn']['ovn_sb_private_key'])
                self.assertEqual('/etc/ovn/cert_host',
                                 config['ovn']['ovn_sb_certificate'])
                self.assertEqual('/etc/ovn/ovn-dedicated-chassis.crt',
                                 config['ovn']['ovn_sb_ca_cert'])
