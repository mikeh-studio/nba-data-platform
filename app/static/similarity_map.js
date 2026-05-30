(function () {
  "use strict";

  // Warm, high-contrast palette that reads against the dark theme. Archetypes
  // cycle through these in the order the API returns them (most populous first).
  const ARCHETYPE_COLORS = [
    "#f04e23",
    "#6bc5f2",
    "#5dd39e",
    "#f0c823",
    "#c77dff",
    "#ff6b6b",
    "#4dd0e1",
    "#ffa94d",
    "#9ccc65",
    "#ba68c8",
    "#ff8a65",
    "#7986cb",
  ];

  const FONT_COLOR = "#e7e0d4";
  const GRID_COLOR = "rgba(231, 224, 212, 0.12)";
  const AXIS_BG = "rgba(0, 0, 0, 0)";

  const plotEl = document.getElementById("similarity-plot");
  const metaEl = document.getElementById("map-meta");
  const noteEl = document.getElementById("map-note");

  if (!plotEl) {
    return;
  }

  function setMeta(text) {
    if (metaEl) {
      metaEl.textContent = text;
    }
  }

  function showEmpty(message) {
    plotEl.innerHTML =
      '<div class="similarity-empty meta">' + message + "</div>";
  }

  function markerSizes(players) {
    const games = players.map((p) =>
      typeof p.games_sampled === "number" ? p.games_sampled : 0,
    );
    const min = Math.min(...games);
    const max = Math.max(...games);
    if (!isFinite(min) || !isFinite(max) || max === min) {
      return players.map(() => 7);
    }
    return games.map((g) => 4 + ((g - min) / (max - min)) * 7);
  }

  function hoverText(player) {
    const lines = [];
    lines.push("<b>" + (player.player_name || "Unknown") + "</b>");
    const teamBits = [];
    if (player.team_abbr) {
      teamBits.push(player.team_abbr);
    }
    if (typeof player.games_sampled === "number") {
      teamBits.push(player.games_sampled + " games");
    }
    if (teamBits.length) {
      lines.push(teamBits.join(" · "));
    }
    if (player.archetype_label) {
      lines.push(player.archetype_label);
    }
    if (typeof player.cluster_confidence === "number") {
      lines.push(
        "Cluster fit " + Math.round(player.cluster_confidence * 100) + "%",
      );
    }
    if (Array.isArray(player.top_traits) && player.top_traits.length) {
      lines.push(player.top_traits.join(", "));
    }
    return lines.join("<br>");
  }

  function buildTraces(players, archetypes) {
    const order = archetypes.map((a) => a.archetype_label);
    const byLabel = new Map();
    players.forEach((player) => {
      const label = player.archetype_label || "Unclassified";
      if (!byLabel.has(label)) {
        byLabel.set(label, []);
      }
      byLabel.get(label).push(player);
    });

    // Preserve API archetype ordering, then any labels not in the summary.
    const labels = order.filter((label) => byLabel.has(label));
    byLabel.forEach((_, label) => {
      if (!labels.includes(label)) {
        labels.push(label);
      }
    });

    return labels.map((label, index) => {
      const group = byLabel.get(label);
      return {
        type: "scatter3d",
        mode: "markers",
        name: label + " (" + group.length + ")",
        x: group.map((p) => p.x),
        y: group.map((p) => p.y),
        z: group.map((p) => p.z),
        text: group.map(hoverText),
        customdata: group.map((p) => p.player_id),
        hovertemplate: "%{text}<extra></extra>",
        marker: {
          size: markerSizes(group),
          color: ARCHETYPE_COLORS[index % ARCHETYPE_COLORS.length],
          opacity: 0.85,
          line: { width: 0 },
        },
      };
    });
  }

  function axis(title) {
    return {
      title: { text: title, font: { color: FONT_COLOR } },
      backgroundcolor: AXIS_BG,
      gridcolor: GRID_COLOR,
      zerolinecolor: GRID_COLOR,
      showbackground: true,
      tickfont: { color: FONT_COLOR, size: 10 },
    };
  }

  function render(data) {
    const players = (data.players || []).filter(
      (p) =>
        typeof p.x === "number" &&
        typeof p.y === "number" &&
        typeof p.z === "number",
    );

    if (!players.length) {
      showEmpty(
        "The similarity projection is not available yet. It is published after the next pipeline run.",
      );
      setMeta("No projection data");
      return;
    }

    const archetypes = data.archetypes || [];
    const traces = buildTraces(players, archetypes);

    const layout = {
      paper_bgcolor: AXIS_BG,
      plot_bgcolor: AXIS_BG,
      font: { color: FONT_COLOR },
      margin: { l: 0, r: 0, t: 0, b: 0 },
      showlegend: true,
      legend: {
        font: { color: FONT_COLOR, size: 11 },
        bgcolor: AXIS_BG,
        itemsizing: "constant",
      },
      scene: {
        xaxis: axis("PC1"),
        yaxis: axis("PC2"),
        zaxis: axis("PC3"),
        aspectmode: "cube",
      },
    };

    const config = { responsive: true, displaylogo: false };
    window.Plotly.newPlot(plotEl, traces, layout, config);

    plotEl.on("plotly_click", (event) => {
      if (!event || !event.points || !event.points.length) {
        return;
      }
      const playerId = event.points[0].customdata;
      if (playerId) {
        window.location.href = "/players/" + playerId;
      }
    });

    setMeta(
      players.length + " players · " + archetypes.length + " archetypes",
    );
    if (noteEl) {
      noteEl.title = "Click a player to open their detail page.";
    }
  }

  function init() {
    if (!window.Plotly) {
      showEmpty("3D rendering library failed to load.");
      setMeta("Unavailable");
      return;
    }
    fetch("/api/similarity-map")
      .then((response) => {
        if (!response.ok) {
          throw new Error("Request failed: " + response.status);
        }
        return response.json();
      })
      .then(render)
      .catch(() => {
        showEmpty("Could not load the similarity projection.");
        setMeta("Error");
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
