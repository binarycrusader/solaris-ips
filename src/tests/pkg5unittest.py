#!/usr/bin/python
#
# CDDL HEADER START
#
# The contents of this file are subject to the terms of the
# Common Development and Distribution License (the "License").
# You may not use this file except in compliance with the License.
#
# You can obtain a copy of the license at usr/src/OPENSOLARIS.LICENSE
# or http://www.opensolaris.org/os/licensing.
# See the License for the specific language governing permissions
# and limitations under the License.
#
# When distributing Covered Code, include this CDDL HEADER in each
# file and include the License file at usr/src/OPENSOLARIS.LICENSE.
# If applicable, add the following below this CDDL HEADER, with the
# fields enclosed by brackets "[]" replaced with your own identifying
# information: Portions Copyright [yyyy] [name of copyright owner]
#
# CDDL HEADER END
#

# Copyright 2008 Sun Microsystems, Inc.  All rights reserved.
# Use is subject to license terms.

import baseline
import copy
import string
import sys
import time
import unittest
import gettext
import os

gettext.install("pkg", "/usr/lib/locale")

OUTPUT_DOTS=0           # Dots ...
OUTPUT_VERBOSE=1        # Verbose
OUTPUT_PARSEABLE=2      # Machine readable

class EarlyTearDownException(Exception):
        """An exception for inidicating early teardown of the testcase is
        desired.  This exception is only useful for testing depot startup and
        whatnot from the test case setUp() functions, and shouldn't be used or
        inherited from for other purposes.  
        """
        pass

class Pkg5TestCase(unittest.TestCase):

        # Needed for compatability
        failureException = AssertionError

        bogus_url = "test.invalid"

        def __init__(self, methodName='runTest'):
                super(Pkg5TestCase, self).__init__(methodName)
                self.__testMethodName = methodName

        def __str__(self):
                return "%s.py %s.%s" % (self.__class__.__module__,
                    self.__class__.__name__, self.__testMethodName)
        def getTeardownFunc(self):
                return (self, self.tearDown)

        def run(self, result=None):
                if result is None:
                        result = self.defaultTestResult()
                result.startTest(self)
                testMethod = getattr(self, self.__testMethodName)
                if result.coverage:
                        self.coverage_cmd, self.coverage_env = result.coverage
                else:
                        self.coverage_cmd, self.coverage_env = "", {}
                try:
                        try:
                                self.setUp()
                        except KeyboardInterrupt:
                                raise
                        except EarlyTearDownException:
                                self.tearDown()
                                result.addSuccess(self)
                                return
                        except:
                                result.addError(self, sys.exc_info())
                                return

                        ok = False
                        try:
                                testMethod()
                                ok = True
                        except self.failureException:
                                result.addFailure(self, sys.exc_info())
                        except KeyboardInterrupt:
                                raise
                        except:
                                result.addError(self, sys.exc_info())

                        try:
                                self.tearDown()
                        except KeyboardInterrupt:
                                raise
                        except:
                                result.addError(self, sys.exc_info())
                                ok = False

                        if ok:
                                result.addSuccess(self)
                finally:
                        result.stopTest(self)

class _Pkg5TestResult(unittest._TextTestResult):
        baseline = None
        machsep = "|"
        def __init__(self, stream, output, baseline, bailonfail=False):
                unittest.TestResult.__init__(self)
                self.stream = stream
                self.output = output
                self.baseline = baseline
                self.success = []
                self.bailonfail = bailonfail

        def addSuccess(self, test):
                unittest.TestResult.addSuccess(self, test)
                bresult = self.baseline.handleresult(str(test), "pass")
                if self.output == OUTPUT_VERBOSE or \
                    self.output == OUTPUT_PARSEABLE:
                        res = ""
                        if bresult == True:
                                res = "pass"
                        else:
                                res = "pass (FAIL)"
                        self.stream.writeln(res)
                elif self.output == OUTPUT_DOTS:
                        self.stream.write('.')
                self.success.append(test)

        def addError(self, test, err):
                unittest.TestResult.addError(self, test, err)
                bresult = self.baseline.handleresult(str(test), "error")
                if self.output == OUTPUT_VERBOSE or \
                    self.output == OUTPUT_PARSEABLE:
                        self.stream.writeln("ERROR")
                        if self.output == OUTPUT_VERBOSE:
                                self.stream.writeln("%s" % self.errors[-1][1])
                elif self.output == OUTPUT_DOTS:
                        if bresult:
                                self.stream.write('e')
                        else:
                                self.stream.write('E')

        def addFailure(self, test, err):
                unittest.TestResult.addFailure(self, test, err)
                bresult = self.baseline.handleresult(str(test), "fail")
                if self.output == OUTPUT_VERBOSE or \
                    self.output == OUTPUT_PARSEABLE:
                        res = ""
                        if bresult == True:
                                res = "FAIL (pass)"
                        else:
                                res = "FAIL"
                        self.stream.writeln(res)
                        if self.output == OUTPUT_VERBOSE:
                                self.stream.writeln("%s" % self.failures[-1][1])
                elif self.output == OUTPUT_DOTS:
                        if bresult:
                                self.stream.write('f')
                        else:
                                self.stream.write('F')
                if self.bailonfail and not bresult:
                    tdf = test.getTeardownFunc()[1]
                    tdf()
                    if test.persistent_depot:
                            test.reallytearDown()
                    raise

        def getDescription(self, test):
                return str(test)

        def startTest(self, test):
                unittest.TestResult.startTest(self, test)
                if not self.output == OUTPUT_DOTS:
                        self.stream.write(
                            string.ljust(self.getDescription(test), 60))
                if self.output == OUTPUT_VERBOSE:
                        self.stream.write("   ")
                elif self.output == OUTPUT_PARSEABLE:
                        self.stream.write(" | ")
                self.stream.flush()

        def printErrors(self):
                self.stream.writeln()
                self.printErrorList('ERROR', self.errors)
                self.printErrorList('FAIL', self.failures)

        def printErrorList(self, flavour, errors):
                for test, err in errors:
                        self.stream.writeln(self.separator1)
                        self.stream.writeln("%s: %s" %
                            (flavour, self.getDescription(test)))
                        self.stream.writeln(self.separator2)
                        self.stream.writeln("%s" % err)

class Pkg5TestRunner(unittest.TextTestRunner):
        """TestRunner for test suites that we want to be able to compare
        against a result baseline."""
        baseline = None
        sep1 = '=' * 70
        sep2 = '-' * 70

        def __init__(self, baseline, stream=sys.stderr, output=OUTPUT_DOTS,
            timing_file=None, bailonfail=False, coverage=None):
                """Set up the runner, creating a baseline object that has
                a name of 'suite'_baseline.pkl, where suite is 'cli', 'api',
                etc."""
                # output is one of "dots", "verbose", "machine"
                super(Pkg5TestRunner, self).__init__(stream)
                self.baseline = baseline
                self.output = output
                self.timing_file = timing_file
                self.bailonfail = bailonfail
                self.coverage = coverage

        def _makeResult(self):
                return _Pkg5TestResult(self.stream, self.output, self.baseline,
                    bailonfail=self.bailonfail)

        def run(self, test):
                "Run the given test case or test suite."
                result = self._makeResult()
                startTime = time.time()
                result.coverage = self.coverage
                test.run(result)
                stopTime = time.time()
                timeTaken = stopTime - startTime
                timing = {}
                lst = []
                for t in test._tests:
                        for (cname, mname), secs in t.timing.items():
                                lst.append((secs, cname, mname))
                                if cname not in timing:
                                        timing[cname] = 0
                                timing[cname] += secs
                lst.sort()
                clst = sorted((secs, cname) for cname, secs in timing.items())
                                        
                if self.output != OUTPUT_VERBOSE:
                        result.printErrors()
                        self.stream.writeln(result.separator2)
                run = result.testsRun
                self.stream.writeln("Ran %d test%s in %.3fs" %
                    (run, run != 1 and "s" or "", timeTaken))
                self.stream.writeln()
                if not result.wasSuccessful():
                        self.stream.write("FAILED (")
                        success, failed, errored, mismatches = map(len,
                            (result.success, result.failures, result.errors,
                                self.baseline.getfailures()))
                        self.stream.write("successes=%d, " % success)
                        self.stream.write("failures=%d, " % failed)
                        self.stream.write("errors=%d, " % errored)
                        self.stream.write("mismatches=%d" % mismatches)
                        self.stream.writeln(")")
                else:
                        self.stream.writeln("OK")

                if self.timing_file:
                        try:
                                fh = open(self.timing_file, "ab+")
                                opened = True
                        except KeyboardInterrupt:
                                raise
                        except Exception:
                                fh = sys.stderr
                                opened = False
                        self.__write_timing_info(fh, clst, lst)
                        if opened:
                                fh.close()

                return result

        @staticmethod
        def __write_timing_info(stream, class_list, method_list):
                if not class_list and not method_list:
                        return
                tot = 0
                for secs, cname in class_list:
                        print >> stream, "%6.2f %s" % (secs, cname)
                        tot += secs
                print >> stream, "%6.2f Total time" % tot
                print >> stream, "=" * 60
                for secs, cname, mname in method_list:
                        print >> stream, "%6.2f %s %s" % (secs, cname, mname)
                print >> stream, "=" * 60
                print >> stream, "=" * 60 + "\n" * 4

class Pkg5TestSuite(unittest.TestSuite):
        """Test suite that handles persistent depot tests.  Persistent depot
        tests are ones that are able to only call their setUp/tearDown
        functions once per class, instead of before and after every test case.
        Aside from actually running the test it defers the majority of its
        work to unittest.TestSuite.

        To make a test class into a persistent depot one, add this class
        variable declaration:
                persistent_depot = True
        """

        def run(self, result):
                self.timing = {}
                inst = None
                tdf = None
                try:
                        persistent_depot = getattr(self._tests[0],
                            "persistent_depot", False)
                except IndexError:
                        # No tests, thats ok.
                        return

                if persistent_depot:
                        inst, tdf = self._tests[0].getTeardownFunc()
                        if result.coverage:
                                inst.coverage_cmd, inst.coverage_env = result.coverage
                        else:
                                inst.coverage_cmd, inst.coverage_env = "", {}
                        try:
                                inst.setUp()
                        except KeyboardInterrupt:
                                raise
                        except:
                                result.addError(inst, sys.exc_info())
                def donothing():
                        pass
                for test in self._tests:
                        if result.shouldStop:
                                break
                        real_test_name = test._Pkg5TestCase__testMethodName
                        cname = test.__class__.__name__
                        # Populate test with the data from the instance
                        # already constructed, but update the method name.
                        # We need to do this so that we have all the state
                        # that the object is populated with when setUp() is
                        # called (depot controller list, etc).
                        if persistent_depot:
                                name = test._Pkg5TestCase__testMethodName
                                test = copy.copy(inst)
                                test._Pkg5TestCase__testMethodName = name
                                # For test classes with persistent_depot set,
                                # make their setup/teardown methods do nothing
                                # since we are calling them here.
                                test.reallytearDown = tdf
                                test.setUp = donothing
                                test.tearDown = donothing
                        test_start = time.time()
                        test(result)
                        test_end = time.time()
                        self.timing[cname, real_test_name] = \
                            test_end - test_start
                if persistent_depot:
                        try:
                                tdf()
                        except KeyboardInterrupt:
                                raise
                        except:
                                result.addError(inst, sys.exc_info())
