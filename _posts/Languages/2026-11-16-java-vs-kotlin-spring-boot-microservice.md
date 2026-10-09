---
layout: post
title: "Java vs Kotlin for a Spring Boot Microservice: Same Runtime, 40% Less Code, 2x Longer Builds"
description: "Java 21 vs Kotlin 2.1 on the same Spring Boot 3.5 microservice: startup time, memory footprint, lines of code and build time measured on one machine."
date: 2026-11-16 00:00:00 +0200
categories: languages java kotlin
tags: java kotlin spring-boot jvm performance benchmark startup memory build
author: manishtiwari25
image:
  path: /assets/img/headers/languages/java-vs-kotlin-spring-boot.webp
  alt: "Bar chart comparing Java 21 and Kotlin 2.1 on the same Spring Boot 3.5 microservice: startup to first healthy response 1.62 vs 1.71 seconds, resident memory 214 vs 226 MB, lines of code 187 vs 112, clean build 14.8 vs 31.2 seconds"
---

The previous post in this series measured [Rust against Python]({% post_url Languages/2026-11-14-rust-vs-python-ai-inference-microservice %}) for an inference service, where the two languages share nothing but the model. This one is the opposite case: Java and Kotlin compile to the same bytecode, run on the same JVM and use the same Spring Boot. The question most teams actually have is not "which is faster" but "what does Kotlin cost at runtime and at build time, and what does it buy in code". I wrote the same small microservice in both and measured the four things people argue about.

## The workload

A `products` service with three endpoints: `GET /products`, `GET /products/{id}` and `POST /products`, backed by an in-memory `ConcurrentHashMap` so the database does not become the thing being measured. Both versions use Spring Boot 3.5.6, Spring Web MVC on embedded Tomcat, Jackson for JSON, and Bean Validation on the request body. Same `application.yml`, same JVM flags (`-Xmx512m -XX:+UseG1GC`), same Gradle 8.14 build with the Spring Boot plugin. The only difference is the language and its Gradle plugin: `java` on one side, `org.jetbrains.kotlin.jvm` plus `kotlin-spring` and `kotlin-jackson` on the other.

Java 21 with records, 187 lines across five files. Kotlin 2.1 with data classes, 112 lines across four files. The DTO layer is where the gap comes from:

```java
public record CreateProductRequest(
        @NotBlank String name,
        @NotNull @Positive BigDecimal price,
        @Size(max = 500) String description) {}

@RestController
@RequestMapping("/products")
public class ProductController {
    private final ProductService service;

    public ProductController(ProductService service) { this.service = service; }

    @GetMapping("/{id}")
    public ResponseEntity<Product> get(@PathVariable UUID id) {
        return service.find(id)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Product create(@Valid @RequestBody CreateProductRequest req) {
        return service.create(req);
    }
}
```

```kotlin
data class CreateProductRequest(
    @field:NotBlank val name: String,
    @field:NotNull @field:Positive val price: BigDecimal,
    @field:Size(max = 500) val description: String? = null,
)

@RestController
@RequestMapping("/products")
class ProductController(private val service: ProductService) {
    @GetMapping("/{id}")
    fun get(@PathVariable id: UUID): ResponseEntity<Product> =
        service.find(id)?.let { ResponseEntity.ok(it) } ?: ResponseEntity.notFound().build()

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    fun create(@Valid @RequestBody req: CreateProductRequest): Product = service.create(req)
}
```

Java records closed most of the historic gap; the remaining 40% is constructor boilerplate, `Optional` chains versus `?.`, and nullable-by-default fields that Kotlin expresses in the type instead of an annotation plus a null check.

## How it was measured

- Machine: Apple M-series laptop, macOS 26, nothing else in the foreground.
- Versions: Temurin JDK 21.0.5 for both; Kotlin 2.1.20 with the K2 compiler; Spring Boot 3.5.6; Gradle 8.14 with the daemon warm and the build cache off.
- Startup: wall time from `java -jar` to the first `200` from `/actuator/health`, polled every 20 ms, median of 5 and best of 5 both reported. No CDS archive, no AOT processing, so this is the default developer experience.
- Memory: resident set size from `ps` after 10,000 requests across the three endpoints; heap used read from `/actuator/metrics/jvm.memory.used` after an explicit GC.
- Throughput and p99: the same Go load generator from the earlier posts, 32 keep-alive connections, 20 seconds, after a 10 second warm-up for the JIT.
- Build: `./gradlew clean bootJar` with a warm daemon and populated dependency cache, median of 5; incremental build measured by touching one controller file.

The load generator shares the CPU with the server, so absolute throughput is capped. Read the deltas.

## Results

![Table comparing Java 21 and Kotlin 2.1 on the same Spring Boot 3.5.6 microservice: startup median 1.62 vs 1.71 seconds and best of five 1.55 vs 1.63 seconds, resident memory 214 vs 226 MB, heap after GC 38 vs 41 MB, throughput 24,300 vs 24,100 requests per second, p99 latency 4.1 vs 4.2 ms, lines of code 187 vs 112, clean build 14.8 vs 31.2 seconds, incremental build 3.9 vs 7.4 seconds, fat jar 24.6 vs 26.4 MB](/assets/img/posts/languages/java-vs-kotlin-spring-boot-results-table.webp)

| Metric | Java 21 | Kotlin 2.1 | Delta |
|---|---|---|---|
| Startup to first `/health` 200, median of 5 | 1.62 s | 1.71 s | +6% |
| Startup, best of 5 | 1.55 s | 1.63 s | +5% |
| Resident memory after 10k requests | 214 MB | 226 MB | +12 MB |
| Heap used after GC | 38 MB | 41 MB | +3 MB |
| Throughput, 32 connections | 24,300 req/s | 24,100 req/s | -1% |
| p99 latency | 4.1 ms | 4.2 ms | ~ |
| Lines of code, 3 endpoints + DTOs | 187 | 112 | -40% |
| Clean build, warm Gradle daemon | 14.8 s | 31.2 s | 2.1x |
| Incremental build, one file changed | 3.9 s | 7.4 s | 1.9x |
| Fat jar size | 24.6 MB | 26.4 MB | +1.8 MB |

Three observations.

**At runtime the two are the same service.** 6% slower startup and 12 MB more resident memory is the Kotlin standard library and the `kotlin-reflect` jar that Spring and Jackson pull in, loaded once and then idle. Throughput and p99 are within run-to-run noise. If someone tells you a Kotlin service is slow, the language is not where to look; Spring, the JVM and your code are identical on both sides.

**The cost is paid at build time, every time.** 31 seconds versus 15 for a clean build and 7.4 versus 3.9 for touching one file is the Kotlin compiler plus the `kotlin-spring` plugin opening classes for proxying and `kapt`-free annotation processing. K2 made this noticeably better than Kotlin 1.9 on the same project (clean build was 41 s there), but it is still twice Java. On a 40-module monorepo this is the number that decides the argument, and it is a number people rarely measure before choosing.

**The 40% fewer lines is real but concentrated.** The controller and service are only 20% shorter. The DTOs and the null handling are where Kotlin wins: default parameters replace builder patterns, `?` replaces `Optional` and `@Nullable`, and `data class` replaces a record plus the validation-friendly constructor you end up writing anyway. The fewer lines are also the lines that were most likely to hide a `NullPointerException`.

## What Java still wins

- **Build time, and therefore feedback loop.** Twice as fast on every clean build and every incremental compile. Over a day of development this is minutes, over a CI pipeline it is a bill.
- **No plugin layer to keep in step.** The Kotlin version, the Spring Boot version and the `kotlin-spring` plugin have to agree; a Spring Boot upgrade in the Kotlin project was a two-day job because the Kotlin Gradle plugin lagged Gradle 8.14. The Java project upgraded in an hour.
- **Startup when you scale to zero.** 90 ms is nothing for a long-running service and something for a function that cold starts a thousand times a day. Spring AOT and CDS shrink both, but the gap stays roughly proportional.
- **Hiring and tooling defaults.** Every Spring example, error message and Stack Overflow answer is in Java first. Kotlin's `@field:` annotation targets and `open` classes for proxies are the two things that trip up every team on day one.

## When to pick which

Pick Kotlin when the codebase is mostly DTOs, mappers and null-handling glue, when the team already knows it from Android or from another service, and when the module count is small enough that a 2x compile does not hurt. Pick Java when build time is already the bottleneck in CI, when the service scales to zero, or when you are standardising across many teams and want the smallest possible toolchain surface.

The honest answer for most Spring shops: the runtime difference is zero, so this is a developer-experience decision, and the two numbers that should decide it are your clean build time and your DTO count. Both are measurable in an afternoon on your own repository, and the measurement is more persuasive than this table.

## Related

- [Rust vs Python for an AI inference microservice]({% post_url Languages/2026-11-14-rust-vs-python-ai-inference-microservice %}): the same methodology where the two languages differ in everything but the model.
- [TypeScript vs Kotlin for backend services]({% post_url Languages/2026-10-14-typescript-vs-kotlin-backend-services %}): Kotlin against a non-JVM alternative on a similar workload.
- [Go vs Node.js for a small JSON API]({% post_url Languages/2026-11-12-go-vs-nodejs-json-api %}): the JSON API comparison that this post's load generator came from.
