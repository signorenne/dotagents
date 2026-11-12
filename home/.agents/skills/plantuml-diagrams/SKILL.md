---
name: plantuml-diagrams
description: "Draws and fixes PlantUML diagrams that read at a glance: one question per diagram, the right diagram type, a bundled palette with day and night colours, a layered compact layout without crossing lines or overlapping labels, and a render-and-look check on every change. Use when creating, fixing, reviewing or cleaning up PlantUML or UML diagrams (sequence, class, component, state, activity; .puml files), or when a document needs a diagram."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# PlantUML diagrams

Goal: a diagram the reader understands in one look: it answers one question, has few elements, no crossing lines, no label on top of another element, and stays readable at page width in light and dark viewers.

## Before drawing

- Write the question the diagram answers and use it as the title ("How an order reaches the warehouse"). One question per diagram; when the answer needs more than about 12 boxes or mixes two kinds of relationship (calls and data flow), split it.
- Pick the type that fits the question: a sequence diagram for a flow over time (it has no layout to go wrong, so prefer it for every "how does X reach Y"), a state diagram for modes and transitions, an activity diagram for steps and decisions, a component diagram for structure and context, a class diagram for the main classes of one layer or area, with their key members and relationships.
- For C4 views (context, container, component), use component diagrams (actor, component, database, package, cloud), not the C4 library: its own styles override the palette.
- One dense diagram usually hides two: who is connected to whom (a structure view) and what happens in what order (one sequence view per main flow). Draw them separately rather than labeling every edge of the structure view with the flow.
- Box text: the name the reader knows (the document's glossary), at most two short lines; details belong in the text around the diagram. A class shows its key members instead: public properties, signals and main operations, about 5, with no getters, setters or private members. Edge labels: one to four words.
- Fewer edges: one plain line (--) instead of two opposite arrows, one labeled edge instead of parallel edges between the same pair, and no edge the question does not need.

## Make it look designed

- Shapes say what each element is: component for a unit of code, database for a store, queue for a bus or queue, actor for a person, node for a machine, cloud for an outside service; rectangle only when nothing else fits.
- Line kinds carry meaning, the same in every diagram of a document: solid arrow (-->) for values or calls in its direction, dashed arrow (..>) for creates or depends on, plain line (--) for a two-way exchange instead of a double-headed arrow. Explain them in a legend (legend right ... endlegend).
- Siblings that belong on one row go in a together { } block.
- Boxes on the same level carry names of similar length; a long name in one box makes the whole level wide.
- Group with packages, not stereotypes: a stereotype label such as <<library>> adds a line to every box and, in class diagrams, stays black at night, so put those elements in a package named after the group. A note that matters goes in the name ("Cache\n(singleton)").
- Class diagrams start with hide empty members and state diagrams with hide empty description, so a box shows only what it holds. A state's detail goes in its description (KeyOff : alarms held), below the state's name, not in a second line of the name.

## Colours: the bundled palette only

Copy palette.iuml into the diagrams folder when it is missing or differs from the bundled one, with the shell (in Claude Code cp ${CLAUDE_SKILL_DIR}/palette.iuml; elsewhere cp ~/.agents/skills/plantuml-diagrams/palette.iuml), because the skill folder may be outside the files you may read, and put !include palette.iuml on the line after @startuml. It sets day colours, and night colours when the diagram is drawn in dark mode (an editor preview on a dark theme renders with -darkmode, and PlantUML then applies the palette's dark block); a rendered SVG for a document carries the day colours. Add no other style, skinparam, theme or inline colour: a fill set without its matching text colour turns unreadable in a dark preview.

## Layout

PlantUML lays these diagrams out with Graphviz, which you steer only indirectly:

- Group boxes by layer or owner with package (for example UI, application logic, outside the app), declared in the order the reader should follow. Layers give the layout its order and the eye a path.
- Keep top to bottom (the default) for layers and flows. Use left to right direction only for a chain of at most about five boxes: longer chains render too wide to read at page width.
- Keep the default curved lines (Bezier splines): never set linetype. Polyline turns them into straight segments, and ortho also draws edge labels on top of boxes and package titles.
- Declare boxes in each layer in the order their edges arrive from the layer above, left to right: Graphviz starts from declaration order, and this alone often removes a crossing.
- Direction hints (-down->, -right->) and hidden links (A -[hidden]right- B) are suggestions Graphviz often ignores, especially inside packages; use them only if the render shows they worked.
- Do not depend on !pragma layout elk: builds without the ELK library fail on it.

## Check every render

1. Render to a scratch folder with plantuml -tpng -o <absolute scratch folder> <file> (without -o, or with a relative one, the image lands next to the source), and the night colours with -tpng -darkmode (-darkmode after the -t option; before it the render stays in day colours). A syntax error or a missing include exits non-zero, a missing Graphviz or layout library exits 0 with a Java stack trace, and all of them still write an image of the error: treat a non-zero exit or any output on stderr as a failure. The output is named after the name on the @startuml line.
2. Look at the PNG and list: line crossings, labels touching another box, edge or title, edges much longer than their neighbors, and the width to height ratio (wider than about 2 to 1 is too small to read at page width). If you cannot view images, say the visual check was not done.
3. Fix the worst problem with one change from the rules above and render again. After three rounds, keep a remaining crossing only if both lines stay easy to follow; otherwise split the diagram.
4. Report what remains (for example "one crossing left, between X and Y").

## Files

One diagram per .puml file, with @startuml <file name> so the output file name is predictable. When a document shows the diagram, render the SVG (plantuml -tsvg) next to the source and keep both in the same commit; render again whenever the source changes.
