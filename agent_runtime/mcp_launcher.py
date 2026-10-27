"""POSIX resource boundary for explicitly trusted MCP executables (not a sandbox)."""
import os
import resource
import sys

cpu_seconds, memory_mb = int(sys.argv[1]), int(sys.argv[2])
resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
# macOS does not consistently enforce RLIMIT_AS; wall-clock, CPU and output
# bounds still apply. Linux provides an additional virtual-memory ceiling.
if sys.platform.startswith('linux'):
    resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024,) * 2)
os.execve(sys.argv[3], sys.argv[3:], dict(os.environ))
