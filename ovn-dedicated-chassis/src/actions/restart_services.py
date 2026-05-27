#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd
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

import datetime
import sys


sys.path.append('actions')
sys.path.append('lib')

from charms.layer import basic
basic.bootstrap_charm_deps()

import charmhelpers.contrib.openstack.deferred_events as deferred_events
import charmhelpers.contrib.openstack.utils as os_utils
import charmhelpers.core.hookenv as hookenv
import charms_openstack.charm

import os_deferred_event_actions

charms_openstack.bus.discover()


def restart_services(args):
    """Restart services.

    :param args: Unused
    :type args: List[str]
    """
    deferred_only = hookenv.action_get("deferred-only")
    services = hookenv.action_get("services").split()
    os_deferred_event_actions.restart_services(args)
    # Clear deferred stops. If the services start time is after the
    # requested stop time we can infer the stop has happened. This is
    # to work around Bug #2012553
    deferred_stops = [
        e
        for e in deferred_events.get_deferred_events()
        if e.action == 'stop']
    for event in deferred_stops:
        start_time = deferred_events.get_service_start_time(event.service)
        deferred_stop_time = datetime.datetime.fromtimestamp(
            event.timestamp)
        if start_time > deferred_stop_time:
            deferred_events.clear_deferred_events([event.service], 'stop')
        else:
            if deferred_only or event.service in services:
                os_utils.restart_services_action([event.service])
                deferred_events.clear_deferred_events([event.service], 'stop')
    with charms_openstack.charm.provide_charm_instance() as charm_instance:
        charm_instance._assess_status()


def main(args):
    hookenv._run_atstart()
    try:
        restart_services(args)
    except Exception as e:
        hookenv.action_fail(str(e))
    hookenv._run_atexit()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
