#!/usr/bin/env python3
"""Master test runner: executes all tests in correct order.

Test Execution Order:
1. test_integration.py - Fast unit tests (no UI, no container)
   - Controller connectivity, imports, config flow, pattern utils, services
2. test_workflow.py - Pattern logic unit tests (no UI, no container)
   - Pattern capture, rename, apply logic validation
3. test_user_workflow.py - Complete end-to-end test (container + UI)
   - Container management, onboarding, HACS (automated), integration (from curtiside/oelo_lights_ha), device, patterns

Test Strategy:
- Unit tests: Fast feedback, validate logic without container
- End-to-end test: Complete user workflow validation

All tests run sequentially. Unit tests run first for fast feedback.

Usage:
    python3 test/run_all_tests.py
    
    # Or via Makefile:
    make test-all

Configuration:
    Environment variables:
        HA_URL: Home Assistant URL (default: http://localhost:8123)
        CONTROLLER_IP: Oelo controller IP (default: 10.16.52.41)
        HA_TOKEN: Long-lived access token (optional)
        HA_USERNAME: Username (if not using token)
        HA_PASSWORD: Password (if not using token)

See DEVELOPER.md for complete testing architecture and setup instructions.
"""

import asyncio
import subprocess
import sys
import os
import time
from typing import Tuple

TEST_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(TEST_DIR)


def cleanup_test_containers():
    """Clean up any leftover test containers."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "name=ha-test-run"],
            capture_output=True,
            timeout=10
        )
        if result.returncode == 0:
            output = result.stdout.decode().strip()
            if output:
                container_ids = [cid for cid in output.split('\n') if cid.strip()]
                for cid in container_ids:
                    try:
                        subprocess.run(["docker", "stop", cid], capture_output=True, timeout=5)
                        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=5)
                    except:
                        pass
    except:
        pass


def run_test(test_file: str, description: str) -> Tuple[bool, str]:
    """Run a test file and return success status and output.
    
    Args:
        test_file: Name of test file to run
        description: Description of what this test does
        
    Returns:
        tuple: (success: bool, output: str)
    """
    print("\n" + "="*70)
    print(f"TEST: {description}")
    print(f"File: {test_file}")
    print("="*70)
    
    test_path = os.path.join(TEST_DIR, test_file)
    if not os.path.exists(test_path):
        return False, f"Test file not found: {test_path}"
    
    # Cleanup before running test
    cleanup_test_containers()
    
    # Run test in test container
    try:
        # For unit tests, can run directly in test container
        # For end-to-end test, it manages containers itself
        result = subprocess.run(
            ["docker-compose", "run", "--rm", "test", "python3", "-u", f"/tests/{test_file}"],
            cwd=PROJECT_ROOT,
            timeout=600  # 10 minute timeout for end-to-end test
        )
        
        success = result.returncode == 0
        output = f"Exit code: {result.returncode}"
        
        # Cleanup after test
        cleanup_test_containers()
        
        return success, output
    except subprocess.TimeoutExpired:
        print("✗ Test timed out")
        cleanup_test_containers()
        return False, "Test timed out"
    except Exception as e:
        print(f"✗ Error running test: {e}")
        cleanup_test_containers()
        return False, str(e)


def wait_for_ha_ready(max_wait=120):
    """Wait for Home Assistant to be ready."""
    import requests
    print("Waiting for Home Assistant to be ready...")
    for i in range(max_wait):
        try:
            resp = requests.get("http://localhost:8123/api/", timeout=2)
            if resp.status_code in [200, 401]:
                print(f"✓ Home Assistant is ready (after {i*2} seconds)")
                return True
        except:
            pass
        time.sleep(2)
    print(f"✗ Home Assistant not ready after {max_wait*2} seconds")
    return False


def main():
    """Run all tests in correct order."""
    print("="*70)
    print("Oelo Lights - Complete Test Suite")
    print("="*70)
    print("\nThis will run all tests in sequence:")
    print("1. test_integration.py - Fast unit tests")
    print("2. test_workflow.py - Pattern logic unit tests")
    print("3. test_user_workflow.py - Complete end-to-end test")
    print("\n" + "="*70)
    
    # Cleanup before starting
    print("\n=== Pre-test Cleanup ===")
    cleanup_test_containers()
    
    # Wait for HA to be ready
    if not wait_for_ha_ready():
        print("\n✗ Cannot proceed - Home Assistant not ready")
        print("   Start HA first: make start")
        return 1
    
    results = []
    test_results = []
    
    # Test 1: Unit tests (fast, no container)
    success, output = run_test(
        "test_integration.py",
        "Unit Tests - Basic functionality validation"
    )
    results.append(success)
    test_results.append(("test_integration.py", success, output))
    
    if not success:
        print("\n⚠️  Unit tests failed - continuing with remaining tests")
    
    # Test 2: Pattern logic tests (fast, no container)
    success, output = run_test(
        "test_workflow.py",
        "Pattern Logic Tests - Pattern capture/rename/apply logic"
    )
    results.append(success)
    test_results.append(("test_workflow.py", success, output))
    
    # Test 3: End-to-end test (container + UI)
    success, output = run_test(
        "test_user_workflow.py",
        "End-to-End Test - Complete user workflow (container + UI)"
    )
    results.append(success)
    test_results.append(("test_user_workflow.py", success, output))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, success, output in test_results:
        status = "✓ PASSED" if success else "✗ FAILED"
        print(f"{status}: {test_name}")
    
    print("\n" + "-"*70)
    passed = sum(results)
    total = len(results)
    print(f"Total: {passed}/{total} tests passed")
    
    # Final cleanup
    print("\n=== Final Cleanup ===")
    cleanup_test_containers()
    
    if passed == total:
        print("\n✓ ALL TESTS PASSED")
        return 0
    else:
        print(f"\n✗ {total - passed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
