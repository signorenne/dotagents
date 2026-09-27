---
name: event-driven-ui
description: "Designs and fixes event-based concurrency in applications with a UI or render loop, so the UI thread never blocks: one owning thread per piece of state, file writes, I/O and heavy computation on long-lived worker threads with results back as events, bounded queues with an overflow policy, coalesced bursts and budgeted handling, superseded work dropped, crash-safe file writes, and checks that keep it so. Use when a UI freezes, lags, stutters or drops frames and the blocking work is known (an unexplained freeze goes to systematic-debugging first), when work must move off the UI or render thread, or when designing or reviewing threads, queues, workers or event loops in a graphical or embedded application."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Event-driven UI

Goal: the UI or render thread only reacts to events and draws, so no frame is late because of work that could run elsewhere. This covers threads and events inside one process, not messaging between services. When the cause of a freeze or stutter is not yet measured, find it first with the systematic-debugging skill (Slowness); this skill gives the design and the remedy once the blocking work is known.

## When one loop is enough

Measure first: frame times, the event loop's lateness, CPU per thread. If every handler fits easily in the frame budget (16.6 ms at 60 Hz, shared with layout and drawing), keep one loop and use the platform's asynchronous APIs. Add a thread only for work that blocks (file, network, device I/O) or needs more CPU than a frame allows.

## Who owns what

- Every piece of mutable state has one owning thread, and only that thread writes it. Other threads send it messages; they never call its objects, or the UI's.
- Use few long-lived threads, one per role (input reader, persistence writer, audio, heavy computation), or a pool where the tasks of one owner run in sequence. Never start a thread per request.
- Prefer that ownership to locks. When a lock is unavoidable, hold it only to swap data in or out, never across I/O, a callback or a wait.
- Keep the render thread's state apart from the UI's: copy what a frame needs at one synchronization point.
- Keep threads that must react fast (audio, input) apart from threads that block, and let them share no lock. Where one is unavoidable, use a lock with priority inheritance: otherwise medium-priority work can delay the lock's holder, and with it the fast thread, without bound.

## The UI thread never waits

Nothing on the UI thread reads or writes files, talks to the network or a device, makes a blocking call to another process, waits for a worker's result or lock, or computes for more than a small part of a frame (decoding a large image counts). That includes work after startup, such as a configuration file read again after it changed.

Work goes out as a message to its worker, and the result comes back as an event its owner handles; the UI thread never polls or sleeps waiting for it.

## Queues between threads

- Every queue is bounded. Choose per stream what happens when it is full: keep only the latest value (states, readings), drop the oldest or the newest (logs, repeatable commands), or make the producer wait (data that must not be lost), but never the UI thread: when data the UI thread produces must not be lost and its queue is full, refuse the action visibly. Count what is dropped and log the counts at a limited rate.
- Coalesce bursts: wake the consumer once per batch, not once per item, and let a newer value for the same key replace a pending one (a second save of the same file replaces the first).
- On the UI thread, handle a batch up to a limit of items or time, then return to the loop and continue at the next turn, so a flood of events cannot cost a frame.

## Stale work

When a newer request supersedes an older one (a new search, the next theme, the latest position), cancel the older one: remove it if it has not started, and signal cancellation that long work checks between steps if it has. Tag each request and drop any result whose tag is no longer current, since a task can finish before it sees the signal.

## Files

Writes go through a writer thread, coalesced per file and retried after a delay when they fail. Write crash-safe: a temporary file in the same directory with the target's mode and owner, flush and fsync it, rename it over the target, then fsync the directory; remove the temporary file on failure.

## Errors and shutdown

- No exception crosses into the event loop or out of a worker's task: catch it at the task boundary and report it as an event or a log line.
- Shut down in order: stop the producers, let each worker drain or drop its queue within a deadline, then join it; past the deadline, log it and leave the thread to end with the process. Never kill a thread, and never wait for one without a bound.

## Tests and checks

- Inject the clock and the executors: tests advance virtual time, run queued tasks explicitly and wait on conditions, never sleep. A component that reads the real clock makes its tests slow and flaky.
- In debug builds, assert the owning thread at each entry point of owned state. Turn on the platform's detectors where they exist, for blocking calls on the main thread (Android StrictMode) and for UI calls from other threads (Apple's Main Thread Checker), and run the tests under ThreadSanitizer in a CI job.
- Keep a way to measure the UI thread's lateness and the frame times, and compare them before and after a change that adds or moves work.

For Qt, apply this with the qt-quick skill.
