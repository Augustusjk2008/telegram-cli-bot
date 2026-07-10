export class WeightedLruCache<K, V> {
  private readonly entries = new Map<K, { value: V; weight: number }>();
  private totalWeight = 0;

  constructor(private readonly options: { maxEntries: number; maxWeight: number; weigh: (value: V, key: K) => number }) {}

  get(key: K): V | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.value;
  }

  set(key: K, value: V) {
    const weight = Math.max(0, this.options.weigh(value, key) || 0);
    const previous = this.entries.get(key);
    if (previous) this.totalWeight -= previous.weight;
    this.entries.delete(key);
    this.entries.set(key, { value, weight });
    this.totalWeight += weight;
    while (this.entries.size > this.options.maxEntries || this.totalWeight > this.options.maxWeight) {
      const oldest = this.entries.entries().next().value as [K, { value: V; weight: number }] | undefined;
      if (!oldest) break;
      this.entries.delete(oldest[0]);
      this.totalWeight -= oldest[1].weight;
    }
  }

  get size() { return this.entries.size; }
  get weight() { return this.totalWeight; }
  clear() { this.entries.clear(); this.totalWeight = 0; }
}