"use client";

import { line as d3Line, curveCatmullRom } from "d3";
import { Globe2, MapPinned, ShieldAlert } from "lucide-react";
import {
  ComposableMap,
  Geographies,
  Geography,
  Graticule,
  Marker,
  Sphere,
} from "react-simple-maps";

import type { TransactionFeedItem } from "@/components/TransactionFeed";

type TransactionMapProps = {
  entries: TransactionFeedItem[];
};

type Coordinates = [number, number];
type MapProjection = (coordinates: Coordinates) => [number, number] | null;
type MapGeography = {
  rsmKey: string;
} & Record<string, unknown>;

const GHOST_BANK_HQ = {
  city: "Toronto",
  label: "Ghost Bank HQ",
  coordinates: [-79.3832, 43.6532] as Coordinates,
};

const WORLD_LANDMASSES = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "North America" },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [-168, 72],
            [-145, 72],
            [-130, 64],
            [-122, 52],
            [-118, 34],
            [-107, 22],
            [-90, 10],
            [-68, 18],
            [-58, 45],
            [-75, 60],
            [-108, 68],
            [-140, 66],
            [-168, 72],
          ],
        ],
      },
    },
    {
      type: "Feature",
      properties: { name: "South America" },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [-81, 12],
            [-70, 8],
            [-60, -8],
            [-55, -22],
            [-58, -40],
            [-67, -54],
            [-76, -30],
            [-80, -6],
            [-81, 12],
          ],
        ],
      },
    },
    {
      type: "Feature",
      properties: { name: "Europe" },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [-10, 35],
            [4, 36],
            [18, 41],
            [31, 47],
            [40, 57],
            [28, 66],
            [10, 60],
            [0, 54],
            [-10, 35],
          ],
        ],
      },
    },
    {
      type: "Feature",
      properties: { name: "Africa" },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [-17, 35],
            [12, 37],
            [32, 28],
            [40, 10],
            [42, -8],
            [32, -35],
            [14, -35],
            [0, -25],
            [-10, 0],
            [-17, 20],
            [-17, 35],
          ],
        ],
      },
    },
    {
      type: "Feature",
      properties: { name: "Asia" },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [28, 38],
            [50, 54],
            [72, 62],
            [104, 72],
            [142, 62],
            [150, 44],
            [128, 20],
            [106, 6],
            [94, 2],
            [74, 8],
            [58, 20],
            [42, 26],
            [28, 38],
          ],
        ],
      },
    },
    {
      type: "Feature",
      properties: { name: "Oceania" },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [110, -10],
            [124, -12],
            [142, -18],
            [154, -28],
            [146, -42],
            [128, -41],
            [114, -30],
            [110, -10],
          ],
        ],
      },
    },
  ],
} as const;

const CITY_COORDINATES: Record<string, Coordinates> = {
  toronto: [-79.3832, 43.6532],
  montreal: [-73.5673, 45.5017],
  mississauga: [-79.6441, 43.589],
  hamilton: [-79.8711, 43.2557],
  vancouver: [-123.1207, 49.2827],
  brampton: [-79.7624, 43.7315],
  winnipeg: [-97.1384, 49.8954],
  calgary: [-114.0719, 51.0447],
  lagos: [3.3792, 6.5244],
  moscow: [37.6173, 55.7558],
  bucharest: [26.1025, 44.4268],
  shenzhen: [114.0579, 22.5431],
};

const COUNTRY_COORDINATES: Record<string, Coordinates> = {
  canada: [-95, 58],
  russia: [105, 61],
  nigeria: [8.6753, 9.082],
  china: [103.8198, 35.8617],
  romania: [24.9668, 45.9432],
  "united states": [-98.5795, 39.8283],
};

function normalizeKey(value: string): string {
  return value.trim().toLowerCase();
}

function resolveCoordinates(city: string, country: string): Coordinates | null {
  const cityMatch = CITY_COORDINATES[normalizeKey(city)];
  if (cityMatch) {
    return cityMatch;
  }

  return COUNTRY_COORDINATES[normalizeKey(country)] || null;
}

function buildRoutePath(
  origin: Coordinates,
  destination: Coordinates,
  projection: MapProjection,
): string | null {
  const projectedOrigin = projection(origin);
  const projectedDestination = projection(destination);

  if (!projectedOrigin || !projectedDestination) {
    return null;
  }

  const [originX, originY] = projectedOrigin;
  const [destinationX, destinationY] = projectedDestination;
  const distance = Math.hypot(destinationX - originX, destinationY - originY);
  const arcHeight = Math.min(96, Math.max(18, distance * 0.22));
  const midpoint: [number, number] = [
    (originX + destinationX) / 2,
    (originY + destinationY) / 2 - arcHeight,
  ];
  const points = [projectedOrigin, midpoint, projectedDestination];

  return (
    d3Line()
      .x((point: [number, number]) => point[0])
      .y((point: [number, number]) => point[1])
      .curve(curveCatmullRom.alpha(0.65))(points) || null
  );
}

function estimateRouteLength(
  origin: Coordinates,
  destination: Coordinates,
  projection: MapProjection,
): number {
  const projectedOrigin = projection(origin);
  const projectedDestination = projection(destination);
  if (!projectedOrigin || !projectedDestination) {
    return 0;
  }

  return Math.hypot(
    projectedDestination[0] - projectedOrigin[0],
    projectedDestination[1] - projectedOrigin[1],
  ) * 1.35;
}

export function TransactionMap({ entries }: TransactionMapProps) {
  const visibleEntries = entries.slice(0, 28);
  const visibleFraudCount = visibleEntries.filter(
    (entry) => entry.transaction.is_fraud,
  ).length;

  return (
    <section className="app-panel p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-slate-500">
            Section World
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-50">
            Transaction origin routes
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-300">
            A clean view of where activity is coming from.
          </p>
        </div>

        <div className="landing-pill landing-pill-accent rounded-full p-3">
          <Globe2 className="h-5 w-5" />
        </div>
      </div>

      <div className="app-subpanel mt-6 p-4">
        <div className="grid gap-4 lg:grid-cols-[1.12fr_0.88fr]">
          <div className="overflow-hidden rounded-[28px] bg-[linear-gradient(180deg,rgba(13,16,22,0.94),rgba(10,12,17,0.96))] p-3">
            <ComposableMap
              projection="geoEqualEarth"
              projectionConfig={{ scale: 152, center: [8, 18] }}
              width={860}
              height={420}
              className="h-[22rem] w-full"
            >
              <Sphere
                stroke="rgba(148,163,184,0.12)"
                strokeWidth={0.8}
                fill="rgba(2,6,23,0.55)"
              />
              <Graticule
                stroke="rgba(100,116,139,0.12)"
                strokeWidth={0.45}
              />

              <Geographies geography={WORLD_LANDMASSES}>
                {({
                  geographies,
                  projection,
                }: {
                  geographies: MapGeography[];
                  projection: MapProjection;
                }) => (
                  <g>
                    {geographies.map((geography) => (
                      <Geography
                        key={geography.rsmKey}
                        geography={geography}
                        fill="rgba(31,41,55,0.88)"
                        stroke="rgba(148,163,184,0.16)"
                        strokeWidth={0.6}
                      />
                    ))}

                    {visibleEntries
                      .slice()
                      .reverse()
                      .map((entry, index) => {
                        const origin = resolveCoordinates(
                          entry.transaction.location_city,
                          entry.transaction.location_country,
                        );
                        if (!origin) {
                          return null;
                        }

                        const routePath = buildRoutePath(
                          origin,
                          GHOST_BANK_HQ.coordinates,
                          projection,
                        );
                        if (!routePath) {
                          return null;
                        }

                        const routeLength = estimateRouteLength(
                          origin,
                          GHOST_BANK_HQ.coordinates,
                          projection,
                        );
                        const opacity = Math.max(0.16, 0.92 - index * 0.055);
                        const isFraud = entry.transaction.is_fraud;

                        return (
                          <path
                            key={`route-${entry.id}`}
                            d={routePath}
                            fill="none"
                            stroke={isFraud ? "#db8a8a" : "#9ab6e8"}
                            strokeWidth={isFraud ? 1.8 : 1.15}
                            strokeLinecap="round"
                            strokeOpacity={opacity}
                            className={entry.source === "live" ? "map-route-draw" : ""}
                            style={
                              entry.source === "live"
                                ? {
                                    strokeDasharray: routeLength,
                                    strokeDashoffset: routeLength,
                                    animationDelay: `${Math.min(index * 55, 360)}ms`,
                                  }
                                : undefined
                            }
                          />
                        );
                      })}

                    {visibleEntries
                      .slice()
                      .reverse()
                      .map((entry, index) => {
                        const origin = resolveCoordinates(
                          entry.transaction.location_city,
                          entry.transaction.location_country,
                        );
                        if (!origin) {
                          return null;
                        }

                        const projected = projection(origin);
                        if (!projected) {
                          return null;
                        }

                        const [x, y] = projected;
                        const opacity = Math.max(0.18, 0.94 - index * 0.055);
                        const isFraud = entry.transaction.is_fraud;

                        return (
                          <g key={`origin-${entry.id}`} transform={`translate(${x},${y})`}>
                            {isFraud ? (
                              <circle
                                r={8}
                                fill="none"
                                stroke="rgba(219,138,138,0.72)"
                                strokeWidth="1.2"
                                strokeOpacity={opacity}
                                className="map-pulse-ring"
                              />
                            ) : null}
                            <circle
                              r={isFraud ? 4.2 : 3.2}
                              fill={isFraud ? "#db8a8a" : "#9ab6e8"}
                              fillOpacity={opacity}
                              stroke="rgba(255,255,255,0.28)"
                              strokeWidth={0.6}
                            />
                          </g>
                        );
                      })}

                    <Marker coordinates={GHOST_BANK_HQ.coordinates}>
                      <g>
                        <circle
                          r={10}
                          fill="rgba(154,182,232,0.14)"
                          stroke="rgba(154,182,232,0.42)"
                          className="map-hq-pulse"
                        />
                        <circle
                          r={4.5}
                          fill="#9ab6e8"
                          stroke="rgba(255,255,255,0.6)"
                          strokeWidth={0.8}
                        />
                        <text
                          x={14}
                          y={4}
                          fill="#e2e8f0"
                          fontSize={12}
                          fontWeight={600}
                        >
                          {GHOST_BANK_HQ.label}
                        </text>
                      </g>
                    </Marker>
                  </g>
                )}
              </Geographies>
            </ComposableMap>
          </div>

          <div className="space-y-4">
            <div className="app-subpanel p-5">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Route Window
              </p>
              <p className="mt-2 text-2xl font-semibold text-slate-50">
                {visibleEntries.length}
              </p>
              <p className="mt-3 text-sm leading-6 text-slate-400">
                Plotting the newest processed transactions so route brightness
                fades as traffic ages out.
              </p>
            </div>

            <div className="app-subpanel p-5">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Fraud Origins
              </p>
              <p className="mt-2 text-2xl font-semibold text-rose-100">
                {visibleFraudCount}
              </p>
              <p className="mt-3 text-sm leading-6 text-slate-400">
                Red markers pulse to surface risky routes before the scoreboard
                catches up in the next task.
              </p>
            </div>

            <div className="app-subpanel p-5">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Legend
              </p>
              <div className="mt-4 space-y-3 text-sm leading-6 text-slate-300">
                <div className="flex items-center gap-3">
                  <span className="h-3 w-3 rounded-full bg-cyan-400" />
                  Normal transaction origin
                </div>
                <div className="flex items-center gap-3">
                  <span className="relative flex h-3 w-3 items-center justify-center">
                    <span className="absolute h-3 w-3 rounded-full border border-rose-300/80" />
                    <span className="h-2 w-2 rounded-full bg-rose-400" />
                  </span>
                  Fraud origin with pulse ring
                </div>
                <div className="flex items-center gap-3">
                  <MapPinned className="h-4 w-4 text-slate-300" />
                  Routes converge on Toronto HQ
                </div>
                <div className="flex items-center gap-3">
                  <ShieldAlert className="h-4 w-4 text-amber-100" />
                  Older routes fade darker as they age
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
