import { time } from "./api";

export default function TimeRuler({ start = 0, end }: { start?: number; end: number }) {
  return <div className="source-time-ruler" role="group" aria-label="原片時間刻度">
    {[0, .25, .5, .75, 1].map(fraction => <span key={fraction}>{time(start + (end - start) * fraction, end - start <= 10)}</span>)}
  </div>;
}
