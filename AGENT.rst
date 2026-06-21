Overview
========

This is a monorepo for the v1 OVN Juju machine charms:

* ovn-central

* ovn-chassis

* ovn-dedicated-chassis

How to contribute
=================

* Make sure to make a single change per iteration, and validate/test before
  proceeding.

* Each commit should be a logical unit of change.

* Each commit should pass tests individually to allow bisecting.

* The commit message should begin with focus on WHY the change is necessary,
  continue with rationale for choice of approach and alternatives considered.

* Ensure commit message subject is no longer than 70 characters including the
  required trailing dot (`.`).

* Ensure lines in commit message body are no longer than 67 characters.

* When a patch has been created with the assistance of an AI tool, include
  a Assisted-by tag to disclose that fact.  The author of the patch remains
  fully responsible for the content.
  
  * Example:

    .. code-block:: none

       Assisted-by: Name of AI model, Name of AI Code Assistant Agent

* We want composable code and prefer focused single purpose functions/methods
  that can be composed into complex functionality by chaining them together.
  This design principle facilitates context optimization (for humans and agents
  alike), code reuse and testability.

How to build
------------

The charms make use of the charmcraft tool to build and an example of a typical
set of commands is:

.. code-block:: none

   cd charm
   charmcraft clean
   charmcraft pack -v
   
The charmcraft tool creates a pristine LXD container environment in which the
build executes, so any changes to dependencies or build script is managed
through the charmcraft.yaml file.

A build entails compilation of all Python dependencies from source, so allow
ample time for the command to finish.

How to test
-----------

Coverage, lint and unit tests can be executed from the top-level directory of
the monorepo using the consolidated `tox` configuration. For example, you can
run:

.. code-block:: none

   tox -e pep8-central
   tox -e py3-central
   tox -e cover-central

The functional tests can be executed from the top-level directory of the
monorepo using the consolidated `tox` configuration. For example, you can
execute the command `tox -e func-target-central -- noble-caracal` which will
run functional tests using a Ubuntu noble base and no overlay PPA.

After a test run you must remove any juju models that have the 'zaza-' prefix
in their name with the `juju destroy-model` command, otherwise the system
resources will be depleted for subsequent runs.

Dependency management
---------------------

Python dependencies for coverage, lint and unit tests are managed in the
top-level pip requirement file named `test-requirements.txt`.

Python dependencies for the functional tests are managed in the top-level pip
requirement file named `func-test-requirements.txt`.

Python dependencies for the built charm artefact are managed by a file named
build.lock located in the src sub-directory of each individual charm
sub-directory.

Test framework subtrees
-----------------------

The ``tests/lib`` directory hosts git subtrees of the shared functional
test framework and library code that this monorepo formerly consumed
directly from upstream:

* ``tests/lib/zaza``

  * Upstream: https://github.com/openstack-charmers/zaza.git
  * Tracked branch: ``master``

* ``tests/lib/zaza-openstack-tests``

  * Upstream: https://github.com/openstack-charmers/zaza-openstack-tests.git
  * Tracked branch: ``master``

The subtrees were added with full git history (``git subtree add``
without ``--squash``) so that upstream history remains reachable in this
repository's object database and the subtrees can be synced with
upstream at a later date if so is desired.

When making local changes to code under ``tests/lib``, keep them in
clean, self-contained commits that touch only the subtree in question
and do not interleave with changes to the rest of the monorepo.  This
discipline preserves the ability to later ``git subtree pull`` (or
``push``) against upstream, since subtree operations rely on the
subtree history being a clean continuation of the imported upstream
line.  Mixed commits make such syncs produce conflicts that are hard to
disentangle and effectively forfeit the main benefit of carrying the
subtree locally.
