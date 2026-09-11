# Tools

## 1. Interpolate

This tool has two modes: Path and Area.

In Path mode, the tool interpolates linearly between the terrain elevation at the first and last point of the path.

Usage example: Cut through obstructions in the terrain, build bridges, build ramps.

In Area mode, the tool interpolates the surface between the elevations at the vertices of the polygon.

Usage example: Fill existing ditches or remove dikes.

## 2. Raise path

Interpolates linearly between the terrain elevation at the first and last point of the path, raising the path by a set height.

Features built with this tool will only raise the terrain - the tool will never decrease any elevation value. In other words, it "adds" material to the terrain, never "removes" material.

Side slopes that gently slope downwards from the new path to the existing terrain can be added, see below.

Usage example: Raise a wall that follows the terrain uphill or downhill.

## 3. Lower path

Interpolates linearly between the elevations of the first and last point of the path, lowering the path by a set height.

Features built with this tool will only lower the terrain - the tool will never increase any elevation value. In other words, it "removes" material from the terrain, never "adds" material.

Side slopes that gently slope upwards from the newly cut path to the existing terrain can be added, see below.

Usage example: Create a ditch or culvert that follows the terrain uphill or downhill.


## 4. Raise flat path or area

This tool supports a path as well as an area mode. The path mode creates a flat path raised by a set height over the highest elevation of any of the vertices of the path. The area mode raises an area delineated by a polygon relative to the highest value along the boundary of the entire polygon.

Features built with this tool will only raise the terrain - the tool will never decrease any elevation value. In other words, it "adds" material to the terrain, never "removes" material.

Side slopes that gently slope from the newly raised path or area downwards to the existing terrain can be added, see below.

Usage example: Create a flat dam or wall. In the area mode this can be used to create building outlines.

## 5. Lower flat path or area

This tool supports a path as well as an area mode. The path mode creates a flat path, lowered by a set height relative to the minimum elevation of any of the vertices of the path. The area mode lowers an area delineated by a polygon relative to the lowest elevation value along the entire boundary of the polygon.

Features built with this tool will only lower the terrain - the tool will never increase any elevation value. In other words, it "removes" material from the terrain, never "adds" material.

Side slopes that gently slope from the newly cut path or basin upwards to the existing terrain can be added, see below.

Usage example: Create a flat culvert. In the area mode this can be used to create drainage basins.

## 6. Add to terrain

This tool supports a path as well as an area mode. Both modes increase the elevation at every cell either covered by the path or polygon by a set height.

Usage example: During a storm, inflatable barriers are used to prevent flooding. This tool can simulate the effect of such a barrier.

## 7. Subtract from terrain

This tool supports a path as well as an area mode. Both modes decreases the elevation at every cell either covered by the path or polygon by a set height.

Usage example: Dig a trench into a road (such as for piping or wiring) that follows the slope changes of the road. Deepen a canal so that the terrain reflects the bottom of the canal rather than the water surface.