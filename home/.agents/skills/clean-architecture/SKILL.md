---
name: clean-architecture
description: "Builds and keeps an application in clean architecture with MVVM, as Martin, Evans, Fowler and Cockburn describe it: a pure domain (entities, value objects, aggregates), use cases, repositories whose interfaces the domain owns, DAOs and data sources in infrastructure, view models and views, one composition root, and dependencies that point inward and are checked by the build. Use when the user starts an application (or a module of one), adds a feature across layers, asks where code belongs, or asks to set up, review or enforce the architecture (layers, MVVM, repositories, DAOs, use cases, dependency rules). Not for writing requirements or architecture documents (architecture-doc)."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Clean architecture with MVVM

In an existing project, its own architecture docs and accepted decisions win: report where it departs from this skill instead of migrating it unasked.

## The layers

Every application gets all of them: one folder or module per layer, and inside each one folder per feature.

| Layer | Holds | Depends on |
|---|---|---|
| domain | entities, value objects (immutable, equal by value), aggregates and their invariants, domain services, domain events, and the repository interfaces of the aggregate roots | the language's standard library only |
| application | one use case per user goal, its request and result types, and the ports it needs that the domain does not own (clock, notifications, outside services) | domain |
| infrastructure | the adapters: repository implementations, DAOs and data sources (database, files, network, devices), mappers between stored or transferred records and domain objects, implementations of the application's ports | domain, application |
| presentation | view models (view state, commands, formatting for display) and views | application |
| composition root | creates every concrete object and connects them | everything |

- Dependencies point inward. An interface belongs to the layer that uses it (a repository interface to the domain, as above) and the adapter implements it; adapters never use each other.
- A repository gives collection-like access to an aggregate root in domain terms (orders.byId(id), orders.save(order)), and only aggregates that need direct access get one. A DAO or data source is shaped by the storage (tables, queries, endpoints), stays inside infrastructure, and its records are mapped to domain objects there. Domain objects carry no storage annotations or wire formats.
- Only simple data crosses a boundary: a use case takes a request and returns a result type, never an entity to the view and never a database row to the domain.
- A use case that would only forward one call may be left out, the view model then calling the repository interface directly, only as a decision recorded in the project's decision log with its reason. Presentation then depends on the domain for that interface only, and the view model maps the aggregate to view state at once.

## Data and input flow

- State flows down, events flow up: the view shows view model state through bindings; a user action calls a view model method or command; the view model calls the use case; the result becomes new view model state; the bindings update the view.
- A use case returns its result. When it reports updates over time (a sensor, a subscription, a long job), it pushes them through an output port (a presenter interface or an observable stream) that the view model implements or observes.
- A view model reaches each use case through an interface (an input port), so its tests use a fake.
- A view model never references view types and is tested without the UI. The view holds no policy: no business rules and no formatting decisions, only layout, styling and animation.
- A change notification fires only when the value really changed.
- Each object belongs to one thread. UI objects are touched only from the UI thread; other threads hand their data over through the framework's queued delivery.

## Composition root

One place near the entry point creates the adapters, repositories, use cases and view models in dependency order and passes each its dependencies through its constructor. Nothing else creates them or looks them up: no service locator, no global registry. A large app composes by feature: each feature builds its own parts and receives what it needs from other features as interfaces.

## Enforce it in the build

Turn the dependency rules into checks that fail the gates:

- one build target or module per layer, each linking only what its layer may use;
- inner layers built without the UI framework and the storage libraries;
- a test or script that fails on a forbidden import: ArchUnit, import-linter, dependency-cruiser, or, for C and C++, a script over the compiler's dependency output, because shared include paths let any layer include any header.

Run them in CI, not only by hand. When adopting the rules in an existing codebase, record today's violations as a baseline the check allows and fail only on new ones.

## Adding a feature

Under spec or implement, these are the plan's steps.

1. Domain: the entities, value objects and rules it needs, with unit tests that need no framework.
2. Application: the use case, its request and result types and any new port, tested with fakes of the ports.
3. Infrastructure: the adapters and mappers for those ports, with integration tests against the real storage or service.
4. Presentation: the view model, tested with a fake use case, then the view.
5. Composition root: create and connect the new parts.
6. Run the layer checks and the gates.

For Qt and QML, apply this with the qt-quick skill.
