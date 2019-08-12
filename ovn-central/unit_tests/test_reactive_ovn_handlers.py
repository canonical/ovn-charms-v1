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

import mock

import reactive.ovn_handlers as handlers

import charms_openstack.test_utils as test_utils


class TestRegisteredHooks(test_utils.TestRegisteredHooks):

    def test_hooks(self):
        defaults = [
            'charm.installed',
            'config.changed',
            'update-status',
            'upgrade-charm']
        hook_set = {
            'when': {
                'request_certificates': ('certificates.available',),
            },
            'when_any': {
                'render': ('certificates.ca.changed',
                           'certificates.server.certs.changed',),
            },
        }
        # test that the hooks were registered via the
        # reactive.ovn_handlers
        self.registered_hooks_test_helper(handlers, hook_set, defaults)


class TestOvnHandlers(test_utils.PatchHelper):

    def setUp(self):
        super().setUp()
        # self.patch_release(octavia.OctaviaCharm.release)
        self.charm = mock.MagicMock()
        self.patch_object(handlers.charm, 'provide_charm_instance',
                          new=mock.MagicMock())
        self.provide_charm_instance().__enter__.return_value = \
            self.charm
        self.provide_charm_instance().__exit__.return_value = None

    def test_request_certificates(self):
        self.patch_object(handlers.cert_utils, 'get_certificate_request')
        self.get_certificate_request.return_value = {
            'cert_requests': {
                'aCn': {'sans': 'aSans'},
            },
        }
        self.patch('charms.reactive.set_flag', 'set_flag')
        tls_relation = mock.MagicMock()
        handlers.request_certificates(tls_relation)
        tls_relation.add_request_server_cert.assert_called_once_with(
            'aCn', 'aSans')
        tls_relation.request_server_certs.assert_called_once_with()
        self.set_flag.assert_called_once_with('certificates.connected')
        self.charm.assess_status.assert_called_once_with()

    def test_render(self):
        self.patch('charms.reactive.clear_flag', 'clear_flag')
        handlers.render('arg1', 'arg2')
        self.charm.render_with_interfaces.assert_called_once_with(
            ('arg1', 'arg2'))
        self.clear_flag.assert_has_calls([
            mock.call('certificates.ca.changed'),
            mock.call('certificates.server.certs.changed'),
        ])
        self.charm.assess_status.assert_called_once_with()
