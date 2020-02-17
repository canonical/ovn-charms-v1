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
import inspect

import charmhelpers.fetch as ch_fetch

import charms.ovn_charm


class OVNSubordinateChassisCharm(object):
    """Mix-in for subordinate-specific handling."""

    @staticmethod
    def get_os_codename_package(package, codenames, fatal=True):
        """Override to conditionally decide based on packages in apt cache.

        Please inspect parent method for documentation of parameters.

        The parent method also requires a package to already be installed,
        and on initial charm deploy the fall back is to retrieve information
        from a source configuration option.

        Since we are a subordinate charm, we do not have a source configuration
        option, thus we want to make the decision based on what is currently
        available in the system APT cache alone. Our principle charm should
        already have configured the system with the desired UCA pocket enabled.
        """
        # When the method is called outside of the context of the select
        # release handler we do want it to assert presence of an installed
        # package, as it is then used to detect available upgrades.
        if (not inspect.currentframe().f_back.f_code.co_name == ''
                'default_select_release'):
            return super().get_os_codename_package(
                package, codenames, fatal=fatal)

        cache = ch_fetch.apt_cache()
        try:
            pkg = cache[package]
        except KeyError:
            if not fatal:
                return
            raise ValueError(
                'Could not determine version of package with no installation '
                'candidate: {}'.format(package))
        ver = ch_fetch.apt_pkg.upstream_version(pkg.version)
        major_ver = ver.split('.')[0]
        if (package in codenames and
                major_ver in codenames[package]):
            return codenames[package][major_ver]


class TrainOVNChassisCharm(OVNSubordinateChassisCharm,
                           charms.ovn_charm.BaseTrainOVNChassisCharm):
    # OpenvSwitch and OVN is distributed as part of the Ubuntu Cloud Archive
    # Pockets get their name from OpenStack releases
    release = 'train'
    name = 'ovn-chassis'


class UssuriOVNChassisCharm(OVNSubordinateChassisCharm,
                            charms.ovn_charm.BaseUssuriOVNChassisCharm):
    # OpenvSwitch and OVN is distributed as part of the Ubuntu Cloud Archive
    # Pockets get their name from OpenStack releases
    release = 'ussuri'
    name = 'ovn-chassis'
