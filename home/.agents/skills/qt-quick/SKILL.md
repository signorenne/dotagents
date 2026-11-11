---
name: qt-quick
description: "Qt 6 Quick and QML facts that coding agents get wrong, and the Qt way to apply clean MVVM: view models exposed without context properties, bindable properties, threads and qmllint; which SVG features Qt draws by version; crisp images (sourceSize, pixel ratio, mipmap, whole pixels); asynchronous loading that really is asynchronous; values inherited down the item tree. Use when writing, reviewing or debugging Qt Quick or QML code, the C++ view models behind QML views, or SVG and image assets for a Qt app."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Qt Quick

Find the project's Qt version first (the find_package version in CMake, or the SDK): several facts below depend on it. They were checked against the Qt 6.8 and 6.12 sources; for anything else, read the documentation and source of the project's version rather than relying on memory.

## MVVM in Qt

The layers come from the clean-architecture skill; in Qt they look like this. The domain and application layers use no Qt, not even QtCore: Qt starts in infrastructure, presentation and the composition root.

- QML is the view and the view model is C++. C++ never reaches into QML objects (findChild, setting properties on items) outside tests.
- No context properties: qmllint, the QML compiler and the language server cannot see them. Give each view its view model as a typed required property (required property CartViewModel model), set by the parent item or from C++ with setInitialProperties; for state that is truly app-wide, use a QML_SINGLETON type with no default constructor (the engine prefers one over create()) whose static create() returns the instance the composition root made, after QJSEngine::setObjectOwnership(instance, QJSEngine::CppOwnership), so the engine never deletes it.
- Register view models with QML_ELEMENT or QML_NAMED_ELEMENT in a qt_add_qml_module target. A view model whose constructor takes its dependencies is also QML_UNCREATABLE: the composition root creates it, QML only uses the type.
- With Qt 6 bindable properties, which notify only on a real change, the type needs operator==, a hand-written setter writes the value on every path (no early return when it is equal), and a bindable property is never an algorithm's temporary. The bindable system is not thread-safe.
- Input: QML calls a Q_INVOKABLE method or public slot of the view model, which calls the use case. React to the control's interaction signals (for example moved), not to valueChanged, which also fires when the model updates the control.
- Threads: a worker never touches a GUI-thread object; it hands data over with a queued connection, QCoreApplication::postEvent, or a queue the GUI thread drains.
- Run qmllint on every QML module in the gates (the all_qmllint target, warnings failing the run through .qmllint.ini or --max-warnings). A project rule such as no colour literals in views can be a qmllint plugin or a short script in the gates.

## SVG in Qt

Qt Quick Image draws SVG through Qt SVG: SVG 1.2 Tiny plus, since Qt 6.7, some SVG 1.1 features. It skips the rest without a warning, so render each asset with Qt itself (grab the Image offscreen), never only in a browser.

- Filters: Qt 6.8 draws feFlood, feColorMatrix, feGaussianBlur, feOffset, feComposite and feMerge; feBlend only from 6.9. One unsupported primitive drops the whole filter and the element is drawn unfiltered. Design tool exports often build a drop shadow with feBlend: on 6.8, rewrite it with feMerge (same result for normal blending) or keep the art as a raster.
- clip-path is ignored, and a clipPath element outside defs is drawn as a visible shape.
- preserveAspectRatio is not read: the viewBox is stretched to width and height. Give the canvas and the viewBox the same shape, one unit per pixel (viewBox="0 0 w h").
- Physical units convert at 90 px per inch, not CSS's 96, and pc is not converted: use px. The root width and height are truncated to whole pixels.
- An embedded image element is a raster and blurs when scaled.
- QT_SVG_DEFAULT_OPTIONS=1 in the environment turns the SVG 1.1 features off everywhere: check it when every filter vanishes at once.

## Crisp images

- An Image rasterizes an SVG at sourceSize times the window's device pixel ratio, or at the SVG's own size times that ratio when sourceSize is unset. Set sourceSize to the drawn size in logical pixels: multiplying it by Screen.devicePixelRatio counts the ratio twice. With both dimensions set, the image is stretched unless fillMode preserves the aspect ratio.
- Raster images (PNG, JPEG) are not multiplied by the ratio and only scale down: ship them at the drawn size times the ratio. A large raster drawn small also costs a long decode.
- Leave mipmap off when the texture matches the drawn size. Mipmapped images leave the texture atlas and are not batched, and on GPUs without non-power-of-two texture support they are rescaled to a power of two.
- Keep positions and sizes on whole pixels: image nodes are not snapped, so an edge on a half pixel blurs over two.
- Changing sourceSize or mipmap reloads the image, and rendering an SVG is slow: set them once.

## Asynchronous loading

- Loader with asynchronous: true, and Component.incubateObject, are asynchronous only when the engine has an incubation controller; without one they build everything in one blocking call. QQuickView, QQuickWidget and a Window loaded by QQmlApplicationEngine install one. A QQmlEngine with a QQuickWindow created in C++, or a QQmlApplicationEngine whose root is an Item, does not: call engine.setIncubationController(window.incubationController()).
- Incubation splits the work between objects, not inside one: a synchronous image decode still blocks its frame. Load large images with asynchronous: true, which decodes on a worker thread.
- Keep the startup page synchronous, so its first frame is complete.

## Values inherited down the item tree

For a value every item in a subtree inherits (a theme, a look, a scale), derive an attached type from QQuickAttachedPropertyPropagator (QtQuickControls2, public since Qt 6.5). It follows visual parents and popups and falls back to the window. attachedParentChange also runs on construction, window change and destruction, and the new parent can be null. attachedChildren() returns raw pointers: a child destroyed while you propagate dangles, so guard each one (QPointer) and run that code once under a sanitizer or valgrind.

## Seeing what the scene graph does

QSG_VISUALIZE=batches, clip, overdraw or changes shows how items are drawn, and QSG_RENDERER_DEBUG=render prints the batches. Clipping is a visual effect, not an optimization: it breaks batching.
