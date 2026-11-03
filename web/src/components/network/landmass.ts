import type { Feature, FeatureCollection, Geometry } from "geojson";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";

import topology from "world-atlas/countries-110m.json";

/**
 * The world's land, bundled rather than fetched (copied from Lanthorn). Countries stay
 * separate: h3 rejects a merged landmass that spans the antimeridian.
 */
export function countryFeatures(): Feature<Geometry>[] {
  const world = topology as unknown as Topology;
  const countries = world.objects.countries as GeometryCollection;
  return (feature(world, countries) as unknown as FeatureCollection<Geometry>).features;
}
