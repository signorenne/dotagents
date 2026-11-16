---
name: plantuml-diagrams
description: "Draws and fixes PlantUML diagrams that read at a glance: one question per diagram, the right diagram type, a bundled palette with day and night colours, a layered compact layout without crossing lines or overlapping labels, a checklist on the source before rendering, and at most three render-and-look checks in day colours. Use when creating, fixing, reviewing or cleaning up PlantUML or UML diagrams (sequence, class, component, state, activity; .puml files), or when a document needs a diagram."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne). See LICENSE.txt"
---

# PlantUML diagrams

Goal: a diagram the reader understands in one look: it answers one question, has few elements, no crossing lines, no label on top of another element, and stays readable at page width in light and dark viewers.

## Before drawing

- Write the question the diagram answers and use it as the title ("How an order reaches the warehouse"). One question per diagram; when the answer needs more than about 12 boxes or mixes two kinds of relationship (calls and data flow), split it.
- Pick the type that fits the question: a sequence diagram for a flow over time (it has the fewest layout problems, so prefer it for every "how does X reach Y"), a state diagram for modes and transitions, an activity diagram for steps and decisions, a component diagram for structure and context, a class diagram for the main classes of one layer or area, with their key members and relationships.
- For C4 views (context, container, component), use component diagrams (actor, component, database, package, cloud), not the C4 library: its own styles override the palette.
- One dense diagram usually hides two: who is connected to whom (a structure view) and what happens in what order (one sequence view per main flow). Draw them separately.
- Box text: the name the reader knows (the document's glossary), at most two short lines; details belong in the text around the diagram. A class shows its key members instead: public properties, signals and main operations, about 5, with no getters, setters or private members. A label on a message, an activity edge, a state transition (its trigger) or a class association (multiplicities and role names): one to four words; component and deployment edges carry none (Layout).
- Fewer edges: one plain line (--) instead of two opposite arrows, one edge instead of parallel edges between the same pair, and no edge the question does not need.

## Make it look designed

- Shapes say what each element is: component for a unit of code, database for a store, queue for a bus or queue, actor for a person, node for a machine, cloud for an outside service; rectangle only when nothing else fits.
- Line kinds carry meaning: each kind of edge in a diagram gets its own style, for example solid arrow (-->) for values or calls in its direction, dashed arrow (..>) for creates or depends on, dotted arrow (-[dotted]->) for a third kind such as runs, plain line (--) for a two-way exchange instead of a double-headed arrow. Set them with the arrow syntax and name each in the diagram's legend (legend right ... endlegend); where two diagrams of the same type in a document show the same kind of edge, draw it in the same style.
- Boxes on the same level carry names of similar length; a long name in one box makes the whole level wide.
- Group with packages, not stereotypes: a stereotype label such as <<library>> adds a line to every box and, in class diagrams, stays black at night, so put those elements in a package named after the group. A note that matters goes in the name ("Cache\n(singleton)").
- Class diagrams start with hide empty members and state diagrams with hide empty description, so a box shows only what it holds. A state's detail goes in its description (KeyOff : alarms held), below the state's name, not in a second line of the name.

## Colours: the bundled palette only

Copy palette.iuml into the diagrams folder when it is missing or differs from the bundled one, with the shell (in Claude Code cp ${CLAUDE_SKILL_DIR}/palette.iuml; elsewhere cp ~/.agents/skills/plantuml-diagrams/palette.iuml), because the skill folder may be outside the files you may read, and put !include palette.iuml on the line after @startuml. It sets day colours, and night colours when the diagram is drawn in dark mode (an editor preview on a dark theme renders with -darkmode, and PlantUML then applies the palette's dark block); a rendered SVG for a document carries the day colours. Add no colour, style, skinparam or theme of your own: a fill set without its matching text colour turns unreadable in a dark preview. Commands that set no colour, such as hide footbox, hide empty members and hidden links, are fine.

## Layout

PlantUML lays out class, component, deployment and state diagrams with Graphviz. Crossings, loops and bent edges come from where Graphviz puts the boxes, not from the line style, so fix them by changing the structure:

- Group boxes by layer or owner with package (for example UI, application logic, outside the app), declared in the order the reader should follow. Layers give the layout its order and the eye a path. Declaration order sets the left to right order only of boxes and packages that no edge places; it does not move boxes whose places the edges fix, so reordering does not remove a crossing.
- Keep top to bottom (the default) for layers and flows. Use left to right direction only for a chain of at most about five boxes: longer chains render too wide to read at page width.
- Two boxes that both lead to the same two targets always cross once: put the two sources in one package and draw one edge from the package to each target (Source --> install), give one target its own row (next rule), or drop an edge. An edge from a package says the package as a whole feeds the target, and the edge table or the text names the members it uses; when the target uses only some members, draw its edges from those boxes instead if the render stays free of defects (crossings, arrowheads that run together).
- Give a box that many edges reach its own row below the others with a hidden link from the lowest box (verify -[hidden]down- hub), so its edges arrive from above instead of across.
- In component and deployment diagrams, put no words on the edges: Graphviz sets a label tight against its line, other lines run over it, and no padding (spaces, blank lines) moves it off; each label also takes a row of its own that bends and lengthens the edges around it. Give each kind of edge its own line style (Make it look designed), and put what each edge carries in a table next to the diagram in the document: from, to and what passes. An edge left out of the drawing to keep it clean keeps its row, marked not drawn, and the legend says the table holds more.
- Put siblings that belong on one row there: in a together { } block when no edge joins them, and with a direction link (spec -right-> decide) when one does, because together does not move boxes joined by an edge. Two boxes of one package that edges reach from outside belong on one row, so no edge bends around the upper one.
- An edge that enters a package from above crosses its title when the target sits under the title: keep titles short, place the target on the right of its row, and write a group of one box into the box ("Close: session-close") instead of a package.
- Direction hints (-down->, -right->) and hidden links (A -[hidden]right- B) are suggestions; keep one only when the render shows it worked.
- Leave linetype unset: ortho keeps the boxes where they are and runs lines through other packages, along each other and across short edges, and polyline keeps them too with angular lines, so neither removes a crossing. Keep nodesep, ranksep and the layout engine at their defaults too: wider spacing and !pragma layout smetana kept the crossings and widened the diagram. Do not depend on !pragma layout elk: builds without the ELK library fail on it.

Sequence and activity diagrams have their own layout and ignore linetype, nodesep, ranksep and the layout engine:

- In a sequence diagram, put the participants that exchange the most messages next to each other, the caller leftmost: a message crosses every lifeline between its ends, and its text lies on them. Put hide footbox on the line after the include; it drops the repeated row of participants at the bottom.
- In an activity diagram, keep each condition to a few words and define it in the text around the diagram: a long condition becomes a tall hexagon of small text. A note may hold the definition only when the legend says notes carry it; a note says what the legend says notes say.

## Check the source, then at most three renders

Before the first render, read the source and fix each item that fails; most defects end here, without an image:

- a title that states the question, and about 12 boxes at most;
- !include palette.iuml on the line after @startuml, and no colour, skinparam, style or theme;
- packages for groups, no stereotypes; hide empty members, hide empty description or hide footbox where the type calls for it;
- no words on component or deployment edges, and at most four words on any other label;
- no two boxes that both lead to the same two targets, and a box that many edges reach on its own row;
- left to right only for a chain of at most about five boxes; linetype, nodesep, ranksep and the layout engine unset.

Then check the render, at most three times per diagram:

1. Render the day colours only, to a scratch folder: plantuml -tpng -o <absolute scratch folder> <file> (without -o, or with a relative one, the image lands next to the source). Skip the night render: the palette holds the night colours, and with no other styling they stay readable. A syntax error or a missing include exits non-zero, a missing Graphviz or layout library exits 0 with a Java stack trace, and all of them still write an image of the error: treat a non-zero exit or any output on stderr as a failure. The output is named after the name on the @startuml line.
2. Look at the PNG and list: line crossings, a label touching a line (its own included), a box or a title, a label nearer another edge than its own, an edge through a package title, two arrows sharing one arrowhead, edges much longer than their neighbors, and the width to height ratio (wider than about 2 to 1 is too small to read at page width). If you cannot view images, say the visual check was not done.
3. Fix the worst problem with one change from the rules above and render again. After the third check, stop: keep a remaining crossing only if both lines stay easy to follow; otherwise split the diagram.
4. Report what remains (for example "one crossing left, between X and Y").

## Files

One diagram per .puml file, with @startuml <file name> so the output file name is predictable. When a document shows the diagram, render the SVG (plantuml -tsvg) next to the source and keep both in the same commit; render again whenever the source changes.
