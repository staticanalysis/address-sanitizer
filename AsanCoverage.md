

AddressSanitizer (as of Clang [r199488](http://llvm.org/viewvc/llvm-project?rev=199488&view=rev))
has a very simple coverage tool built in.
It allows to get function-level, basic-block-level, and edge-level coverage at a very low cost.

# Build and run #
**NEW** As of clang [r221720](https://code.google.com/p/address-sanitizer/source/detail?r=221720) the flag has changed from `-fsanitize=address -mllvm -asan-coverage=N`
to `-fsanitize=address -fsanitize-coverage=N`

  * Compile with `-fsanitize=address -fsanitize-coverage=1` for function-level coverage (very fast)
  * Compile with `-fsanitize=address -fsanitize-coverage=2` for basic-block-level coverage (may have up to 30% slowdown on top of AddressSanitizer)
  * Compile with `-fsanitize=address -fsanitize-coverage=3` for edge-level coverage (up to 40% slowdown). Requires clang [r217106](http://llvm.org/viewvc/llvm-project?rev=217106&view=rev))
  * Compile with `-fsanitize=address -fsanitize-coverage=4` for additional calleer-callee coverage. Requires clang [r220985.](http://llvm.org/viewvc/llvm-project?rev=220985&view=rev))
  * Run with ASAN\_OPTIONS=coverage=1
  * Additionally use `-mllvm -sanitizer-coverage-8bit-counters=1` at compile time and `ASAN_OPTIONS=coverage=1:coverage_counters=1` at run-time to get [Coverage counters](#Coverage_counters.md). Requires clang [r231343](http://llvm.org/viewvc/llvm-project?rev=231343&view=rev).
```
% cat -n cov.cc 
     1  #include <stdio.h>
     2  __attribute__((noinline))
     3  void foo() { printf("foo\n"); }
     4  
     5  int main(int argc, char **argv) {
     6    if (argc == 2)
     7      foo();
     8    printf("main\n");
     9  }
% clang++ -g cov.cc -fsanitize=address -fsanitize-coverage=1 
% ASAN_OPTIONS=coverage=1 ./a.out; ls -l *sancov
main
-rw-r----- 1 kcc eng 4 Nov 27 12:21 a.out.22673.sancov
% ASAN_OPTIONS=coverage=1 ./a.out foo ; ls -l *sancov
foo
main
-rw-r----- 1 kcc eng 4 Nov 27 12:21 a.out.22673.sancov
-rw-r----- 1 kcc eng 8 Nov 27 12:21 a.out.22679.sancov
% 
```


Every time you run an executable instrumented with AsanCoverage
one `*.sancov` file is created during the process shutdown.
If the executable is dynamically linked against instrumented DSOs,
one `*.sancov` file will be also created for every DSO.

The same flag `-fsanitize-coverage=N` works with [MemorySanitizer](https://code.google.com/p/memory-sanitizer/) and LeakSanitizer, but you will need to enable it at run-time with `MSAN_OPTIONS=coverage=1` and `LSAN_OPTIONS=coverage=1` respectively.

# Postprocess #
The format of `*.sancov` files is very simple: they contain 4-byte offsets in the corresponding binary/DSO that were executed during the run.


A simple script `$LLVM/projects/compiler-rt/lib/sanitizer_common/scripts/sancov.py` is provided to dump these offsets:
```
% sancov.py print a.out.22679.sancov a.out.22673.sancov
sancov.py: read 2 PCs from a.out.22679.sancov
sancov.py: read 1 PCs from a.out.22673.sancov
sancov.py: 2 files merged; 2 PCs total
0x465250
0x4652a0
```

You can then filter the output of `sancov.py` through `addr2line --exe ObjectFile`
or `llvm-symbolizer --obj ObjectFile` to get file names and line numbers:
```
% sancov.py print a.out.22679.sancov a.out.22673.sancov 2> /dev/null | llvm-symbolizer --obj a.out
cov.cc:3
cov.cc:5
```

# Edge coverage #
Consider this code:
```
void foo(int *a) {
  if (a)
    *a = 0;
}
```

It contains 3 basic blocks, let's name them A, B, C:
```
A
|\
| \
|  B
| /
|/
C
```
If blocks A, B, and C are all covered we know for certain that the edges A=>B and B=>C were executed,
but we still don't know if the edge A=>C was executed.
Such edges of control flow graph are called [critical](http://en.wikipedia.org/wiki/Control_flow_graph#Special_edges).
The edge-level coverage (-asan-coverage=3) simply splits all critical edges by introducing new dummy blocks and then instruments those blocks:
```
A
|\
| \
D  B
| /
|/
C
```

# Bitset #
When `coverage_bitset=1` run-time [flag](Flags.md) is given, the coverage will also be dumped as a bitset
(text file with 1 for blocks that have been executed and 0 for blocks that were not).
```
% clang++ -fsanitize=address -fsanitize-coverage=3 cov.cc 
% ASAN_OPTIONS=coverage=1:coverage_bitset=1 ./a.out 
main
% ASAN_OPTIONS=coverage=1:coverage_bitset=1 ./a.out 1 
foo
main
% head *bitset*
==> a.out.38214.bitset-sancov <==
01101
==> a.out.6128.bitset-sancov <==
11011%
```

For a given executable the length of the bitset is always the same (well, unless dlopen/dlclose come into play),
so the bitset coverage can be easily used for bitset-based corpus distillation.

# Caller-callee coverage #
(Experimental!)
Every indirect function call is instrumented with a run-time function call that captures caller and callee.
At the shutdown time the process dumps a separate file called `caller-callee.PID.sancov`
which contains caller/callee pairs as pairs of lines (odd lines are callers, even lines are callees)
```
a.out 0x4a2e0c
a.out 0x4a6510
a.out 0x4a2e0c
a.out 0x4a87f0
```

Current limitations:
  * Only the first 14 callees for every caller are recorded, the rest are silently ignored.
  * The output format is not very compact since caller and callee may reside in different modules and we need to spell out the module names.
  * The routine that dumps the output is not optimized for speed
  * Only Linux x86\_64 is tested so far.
  * Sandboxes are not supported.

# Coverage counters #
This experimental feature is inspired by [AFL](http://lcamtuf.coredump.cx/afl/technical_details.txt)'s coverage instrumentation.
With additional compile-time and run-time flags you can get more sensitive coverage information.
In addition to boolean values assigned to every basic block (edge) the instrumentation will collect imprecise counters.
On exit, every counter will be mapped to a 8-bit bitset representing counter ranges:
`1, 2, 3, 4-7, 8-15, 16-31, 32-127, 128+` and those 8-bit bitsets will be dumped to disk.

```
% clang++ -g cov.cc -fsanitize=address -fsanitize-coverage=3  -mllvm -sanitizer-coverage-8bit-counters=1
% ASAN_OPTIONS=coverage=1:coverage_counters=1 ./a.out
% ls -l *counters-sancov
... a.out.17110.counters-sancov
% xxd *counters-sancov
0000000: 0001 0100 01
```

These counters may also be used for in-process coverage-guided fuzzers:
```
include/sanitizer/coverage_interface.h:
```
```
  // The coverage instrumentation may optionally provide imprecise counters.
  // Rather than exposing the counter values to the user we instead map
  // the counters to a bitset.
  // Every counter is associated with 8 bits in the bitset.
  // We define 8 value ranges: 1, 2, 3, 4-7, 8-15, 16-31, 32-127, 128+
  // The i-th bit is set to 1 if the counter value is in the i-th range.
  // This counter-based coverage implementation is *not* thread-safe.

  // Returns the number of registered coverage counters.
  uintptr_t __sanitizer_get_number_of_counters();
  // Updates the counter 'bitset', clears the counters and returns the number of
  // new bits in 'bitset'.
  // If 'bitset' is nullptr, only clears the counters.
  // Otherwise 'bitset' should be at least
  // __sanitizer_get_number_of_counters bytes long and 8-aligned.
  uintptr_t
  __sanitizer_update_counter_bitset_and_clear_counters(uint8_t *bitset);

```

# Output directory #

By default, .sancov files are created in the current working directory.
This can be changed with ASAN\_OPTIONS=coverage\_dir=/path
```
% ASAN_OPTIONS=coverage=1,coverage_dir=/tmp/cov ./a.out foo
% ls -l /tmp/cov/*sancov
-rw-r----- 1 kcc eng 4 Nov 27 12:21 a.out.22673.sancov
-rw-r----- 1 kcc eng 8 Nov 27 12:21 a.out.22679.sancov
```

# Sudden death #

Normally, coverage data is collected in memory and saved to disk when the program exits (with an atexit() handler), when a SIGSEGV is caught, or when sanitizer\_cov\_dump is called.

If the program ends with a signal that ASan does not handle (or can not handle at all, like SIGKILL), coverage data will be lost. This is a big problem on Android, where SIGKILL is a normal way of evicting applications from memory.

With ASAN\_OPTIONS=coverage=1,coverage\_direct=1 coverage data is written to a memory-mapped file as soon as it collected.
```
% ASAN_OPTIONS=coverage=1,coverage_direct=1 ./a.out 
main
% ls
7036.sancov.map  7036.sancov.raw  a.out
% sancov.py rawunpack 7036.sancov.raw 
sancov.py: reading map 7036.sancov.map
sancov.py: unpacking 7036.sancov.raw
writing 1 PCs to a.out.7036.sancov
% sancov.py print a.out.7036.sancov 
sancov.py: read 1 PCs from a.out.7036.sancov
sancov.py: 1 files merged; 1 PCs total
0x4b2bae
```

Note that on 64-bit platforms, this method writes 2x more data than the default, because it stores full PC values instead of 32-bit offsets.

# In-process fuzzing #
Coverage data could be useful for fuzzers and sometimes it is preferable to run a fuzzer in the same process as the code being fuzzed (in-process fuzzer).

You can use `__sanitizer_get_total_unique_coverage()` from `<sanitizer/coverage_interface.h>`
which returns the number of currently covered entities in the program.
This will tell the fuzzer if the coverage has increased after testing every new input.

If a fuzzer finds a bug in the ASan run, you will need to save the reproducer before exiting the process.
Use `__asan_set_death_callback` from `<sanitizer/asan_interface.h>` to do that.

An example of such fuzzer can be found in [the LLVM tree](http://llvm.org/viewvc/llvm-project/llvm/trunk/lib/Fuzzer/README.txt?view=markup).

# Performance #

This coverage implementation is **fast**. 

&lt;BR&gt;


With function-level coverage (`-mllvm -asan-coverage=1`) the overhead is not measurable. 

&lt;BR&gt;


With basic-block-level (`-mllvm -asan-coverage=2`) the overhead varies between 0 and 25%.

|       benchmark    |      cov0   |      cov1|         diff 0-1|      cov2|         diff 0-2|         diff 1-2|
|:-------------------|:------------|:---------|:----------------|:---------|:----------------|:----------------|
|       400.perlbench|      1296.00|      1307.00|         1.01|      1465.00|         1.13|         1.12|
|           401.bzip2|       858.00|       854.00|         1.00|      1010.00|         1.18|         1.18|
|             403.gcc|       613.00|       617.00|         1.01|       683.00|         1.11|         1.11|
|             429.mcf|       605.00|       582.00|         0.96|       610.00|         1.01|         1.05|
|           445.gobmk|       896.00|       880.00|         0.98|      1050.00|         1.17|         1.19|
|           456.hmmer|       892.00|       892.00|         1.00|       918.00|         1.03|         1.03|
|           458.sjeng|       995.00|      1009.00|         1.01|      1217.00|         1.22|         1.21|
|      462.libquantum|       497.00|       492.00|         0.99|       534.00|         1.07|         1.09|
|         464.h264ref|      1461.00|      1467.00|         1.00|      1543.00|         1.06|         1.05|
|         471.omnetpp|       575.00|       590.00|         1.03|       660.00|         1.15|         1.12|
|           473.astar|       658.00|       652.00|         0.99|       715.00|         1.09|         1.10|
|       483.xalancbmk|       471.00|       491.00|         1.04|       582.00|         1.24|         1.19|
|            433.milc|       616.00|       627.00|         1.02|       627.00|         1.02|         1.00|
|            444.namd|       602.00|       601.00|         1.00|       654.00|         1.09|         1.09|
|          447.dealII|       630.00|       634.00|         1.01|       653.00|         1.04|         1.03|
|          450.soplex|       365.00|       368.00|         1.01|       395.00|         1.08|         1.07|
|          453.povray|       427.00|       434.00|         1.02|       495.00|         1.16|         1.14|
|             470.lbm|       357.00|       375.00|         1.05|       370.00|         1.04|         0.99|
|         482.sphinx3|       927.00|       928.00|         1.00|      1000.00|         1.08|         1.08|

# Why another coverage? #
Why did we implement yet another code coverage?
  * We needed something that is lightning fast, plays well with AddressSanitizer, and does not significantly increase the binary size.
  * Traditional coverage implementations based in global counters [suffer from contention on counters](https://groups.google.com/forum/#!topic/llvm-dev/cDqYgnxNEhY).