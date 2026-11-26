// Side-by-side layout for overlapping events in a day column (classic interval-graph colouring).

export type Box = { id: string; start: number; end: number };
export type Placed = { id: string; col: number; cols: number };

export function layoutDay(boxes: Box[]): Map<string, Placed> {
  const sorted = [...boxes].sort((a, b) => a.start - b.start || b.end - a.end);
  const out = new Map<string, Placed>();
  let cluster: { box: Box; col: number }[] = [];
  let clusterEnd = -Infinity;
  const columnsEnd: number[] = [];

  const flush = () => {
    const cols = Math.max(1, ...cluster.map((c) => c.col + 1));
    for (const c of cluster) out.set(c.box.id, { id: c.box.id, col: c.col, cols });
    cluster = [];
    columnsEnd.length = 0;
  };

  for (const box of sorted) {
    if (cluster.length && box.start >= clusterEnd) {
      flush();
      clusterEnd = -Infinity;
    }
    let col = columnsEnd.findIndex((end) => end <= box.start);
    if (col === -1) {
      col = columnsEnd.length;
      columnsEnd.push(box.end);
    } else {
      columnsEnd[col] = box.end;
    }
    cluster.push({ box, col });
    clusterEnd = Math.max(clusterEnd, box.end);
  }
  if (cluster.length) flush();
  return out;
}
