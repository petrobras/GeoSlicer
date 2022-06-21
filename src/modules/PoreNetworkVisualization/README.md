# Pore Network Two-Phase Visualization

Visualizes two-phase flow simulations simulations on the 3D view

## Interface


### Input

1. __Input Model Node__: Choose a Model Node. The model must have been created in the simulation tab with the Create Animation Node option selected.

### Parameters

1. __Show zero log Krel__: Assigns a low non-zero value for zero permeability points for display in the logarithmic scale plot.
2. __Animations step__: Current step of the flow animation.
3. __Run animation__: Automatically increment animation step.
4. __Loop animation__: Return to animation step zero after last step.
5. __Animatin speed__: Set speed of animation.
6. __Clip threshold__: Hide outer layers of animation. Disabled when the animatino node doesen't have the full VTK pipeline (such as when the node is loaded from a scene)