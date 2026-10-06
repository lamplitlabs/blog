---
layout: post
title: "Zig vs C for a Systems Tool: Throughput, Binary Size, Cross-Compiling and Where the Bugs Hide"
date: 2026-10-18 09:00:00 -0500
categories: languages zig c
tags: zig c systems-programming performance benchmark hyperfine cross-compilation
author: manishtiwari25
description: "Zig 0.13 vs C (clang 18) for the same TCP proxy: throughput, binary size, build time, cross-compiling and the memory-safety bugs each one lets through."
image:
  path: /assets/img/headers/languages/zig-vs-c-systems-tool.webp
  alt: "Bar chart comparing Zig and C for the same TCP proxy: throughput 9.4 vs 9.6 Gbit/s, binary size 92 KB vs 41 KB, clean build 1.9 s vs 0.8 s, peak RSS 6.1 MB vs 5.8 MB, cross targets without setup 6 vs 1"
---

The [Rust vs Go CLI post]({% post_url Languages/2026-10-16-rust-vs-go-cli-tool %}) compared two languages that both bring a runtime, a package manager and an opinion about error handling. Systems code further down the stack - a network proxy, an allocator shim, a tiny init - usually ends up in C, because C is what the kernel headers, the toolchains and the existing code speak. Zig is the first language in a long time that targets that exact niche without asking you to leave the C ecosystem.

So, same experiment as before: one small tool written twice. `tinyproxy` accepts a TCP connection, forwards it to an upstream, copies bytes in both directions with `splice`/`sendfile` where available and a plain read/write loop otherwise, and counts bytes per connection. Zig 0.13 in `ReleaseFast` against C compiled with clang 18 at `-O2`, measured on an Apple M2 laptop and re-checked on a Linux x86-64 box.

## The tool under test

- Single-threaded event loop (`kqueue` on macOS, `epoll` on Linux), 64 KB buffers.
- Flags for listen address, upstream address and a `--bench N` mode that pushes N bytes through a loopback connection and exits.
- No third-party libraries in either version: Zig's `std.posix` and `std.net`; C's libc plus the platform headers.

## Runtime: a wash

![Terminal screenshot of hyperfine comparing proxy-zig at 3.641 s mean against proxy-c at 3.566 s mean for a 4 GB loopback copy, 1.02 times faster for C, followed by ls -lh showing 92K and 41K binaries, clean build times of 1.9 s for zig build and 0.8 s for clang, and two zig build cross-compile commands exiting 0](/assets/img/headers/languages/zig-vs-c-hyperfine-terminal.webp)

| | Zig 0.13 | C (clang 18) |
|---|---|---|
| 4 GB loopback copy, mean | 3.64 s (9.4 Gbit/s) | 3.57 s (9.6 Gbit/s) |
| Peak RSS | 6.1 MB | 5.8 MB |
| Binary size (stripped) | 92 KB | 41 KB |
| Clean build | 1.9 s | 0.8 s |
| Cross targets that built with no extra setup | 6 of 6 | 1 of 6 |

A proxy is bound by syscalls and memory copies, not by codegen, and both compilers sit on LLVM. The 2% gap is inside run-to-run noise on the Linux box. If you came here for a throughput winner, there isn't one, and that is the honest result for most systems tools: the language stops mattering once the hot path is a `read`/`write` pair.

## Binary size and build time: C is smaller, both are fast

The 92 KB Zig binary carries `std`'s panic handler, formatted-print machinery and stack-trace support; `-fstrip` plus `ReleaseSmall` brings it to 38 KB, under the C build. The default is bigger because Zig keeps safety checks and useful panics on unless you say otherwise.

Both builds are fast enough that the loop is edit-save-run. Zig's 1.9 s is dominated by compiling the parts of `std` the program touches; the incremental cache turns the second build into 0.3 s.

## Cross-compiling: the headline difference

`zig build -Dtarget=aarch64-linux-musl`, `x86_64-windows-gnu`, `x86_64-linux-gnu.2.28`, `aarch64-macos`, `riscv64-linux-musl`, `wasm32-wasi` - all six produced a binary from one laptop with no sysroot, no cross toolchain and no Docker. Zig ships libc headers and the glibc/musl stubs it needs and resolves them per target.

The C build managed exactly one: the host. Getting `aarch64-linux-musl` needed a musl cross toolchain, and the Windows build needed mingw-w64 and a different `select` loop. This is also the reason `zig cc` is quietly becoming the cross-compiler of choice for C projects that never adopt Zig the language.

## Where the bugs hid

This is the part a benchmark table never shows, so I kept notes while writing both.

- The C version shipped two bugs that the Zig version could not express: an off-by-one when the write buffer wrapped (`buf[len]` past the end, caught by AddressSanitizer a day later) and a `close()` on a file descriptor that had already been closed on the error path.
- Zig's `Debug` and `ReleaseSafe` modes trap the out-of-bounds index at runtime with a stack trace, and `defer posix.close(fd)` made the double close structurally impossible.
- Zig's compiler refused to build until every error from `posix.read` was handled or explicitly propagated with `try`. The C version returned `-1` from four functions whose callers never checked it.
- Zig gave nothing for free on use-after-free: a buffer returned from an arena and used after `arena.deinit()` ran fine until it didn't. Zig has no borrow checker; it is "C with the footguns labelled", not Rust.

| | Zig | C |
|---|---|---|
| Bounds checks | on in Debug/ReleaseSafe, off in ReleaseFast | sanitizers only |
| Error handling | error unions, `try`/`catch`, unused errors are compile errors | return codes, unchecked by default |
| Resource cleanup | `defer`/`errdefer` | goto cleanup, discipline |
| Use-after-free | undetected (allocator-dependent) | undetected |
| Undefined behaviour | mostly trapped in safe modes | silent |
| Calling existing C | `@cImport` a header, done | native |

## Which would I pick?

For new systems code that must ship to several targets - agents, sidecars, embedded tooling, anything a customer downloads for a platform you do not develop on - Zig. Same performance, one build command for every target, and a compiler that forces you to look at every failing syscall. Its cost is a pre-1.0 language whose `std` still moves between releases; budget a morning per Zig upgrade.

For a patch to an existing C codebase, a kernel module, or anything where the reviewers only read C: C, built with `zig cc` if cross-compiling hurts. Rewriting working C into Zig for its own sake buys you labelled footguns and a smaller hiring pool.

If the bug class that worries you is use-after-free or data races rather than bounds and error paths, neither of these is the answer; that is the [Rust]({% post_url Languages/2026-10-16-rust-vs-go-cli-tool %}) trade-off, and the price is the borrow checker.

## Related

- [Rust vs Go for a CLI Tool: Startup, Binary Size, Build Time and the Day-Two Costs]({% post_url Languages/2026-10-16-rust-vs-go-cli-tool %}) - the same method one layer up the stack, where runtimes start to matter.
- [TypeScript vs Kotlin for Backend Services]({% post_url Languages/2026-10-14-typescript-vs-kotlin-backend-services %}) - the application-tier comparison in this category.
- [Python vs Rust in a Hot Loop: What 10 Million Iterations Cost, Measured with hyperfine]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) - the compute-bound case where codegen, not syscalls, decides.
