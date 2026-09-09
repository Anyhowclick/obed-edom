import type { MapsDocument } from "./types";

export type RebaseResult<T> = { value: T; conflicts: string[] };

const MISSING = Symbol("missing");
type Missing = typeof MISSING;
type Node = unknown | Missing;

const clone = <T>(value: T): T => structuredClone(value);
const equal = (left: Node, right: Node) => left === MISSING || right === MISSING ? left === right : JSON.stringify(left) === JSON.stringify(right);
const pathText = (path: string[]) => path.length ? path.join(".") : "document";
const property = (value: Record<string, unknown>, key: string): Node => Object.prototype.hasOwnProperty.call(value, key) ? value[key] : MISSING;

type KeyedArray = { key: (value: Record<string, unknown>) => string | null };

function keyedArray(path: string[]): KeyedArray | null {
  const field = path[path.length - 1];
  if (field === "slides" || field === "churches") return { key: (value) => typeof value.id === "string" && value.id ? value.id : null };
  if (field === "links") {
    return {
      key: (value) => typeof value.from === "string" && value.from && typeof value.to === "string" && value.to ? `${value.from}\u0000${value.to}` : null,
    };
  }
  return null;
}

function keyedValues(value: Node, spec: KeyedArray, path: string[], conflicts: string[]): Map<string, Record<string, unknown>> | null {
  if (value === MISSING) return new Map();
  if (!Array.isArray(value)) {
    conflicts.push(`${pathText(path)}: expected an array`);
    return null;
  }
  const values = new Map<string, Record<string, unknown>>();
  for (const entry of value) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      conflicts.push(`${pathText(path)}: invalid keyed row`);
      return null;
    }
    const key = spec.key(entry as Record<string, unknown>);
    if (!key || values.has(key)) {
      conflicts.push(`${pathText(path)}: missing or duplicate key`);
      return null;
    }
    values.set(key, entry as Record<string, unknown>);
  }
  return values;
}

function validateKeyedShape(value: unknown, path: string[], conflicts: string[]): void {
  const spec = keyedArray(path);
  if (spec && Array.isArray(value)) {
    keyedValues(value, spec, path, conflicts);
  }
  if (Array.isArray(value)) {
    value.forEach((entry, index) => validateKeyedShape(entry, [...path, String(index)], conflicts));
  } else if (value && typeof value === "object") {
    Object.entries(value as Record<string, unknown>).forEach(([key, entry]) => validateKeyedShape(entry, [...path, key], conflicts));
  }
}

function mergeArray(path: string[], base: Node, local: Node, remote: Node, conflicts: string[]): unknown[] {
  const spec = keyedArray(path);
  if (!spec) {
    if (equal(local, base)) return remote === MISSING ? [] : clone(remote as unknown[]);
    if (equal(remote, base) || equal(local, remote)) return local === MISSING ? [] : clone(local as unknown[]);
    conflicts.push(pathText(path));
    return local === MISSING ? [] : clone(local as unknown[]);
  }

  const before = keyedValues(base, spec, path, conflicts);
  const ours = keyedValues(local, spec, path, conflicts);
  const theirs = keyedValues(remote, spec, path, conflicts);
  if (!before || !ours || !theirs) return local === MISSING || !Array.isArray(local) ? [] : clone(local);

  const merged = new Map<string, Record<string, unknown>>();
  const allKeys = new Set([...before.keys(), ...ours.keys(), ...theirs.keys()]);
  for (const key of allKeys) {
    const prior: Node = before.get(key) ?? MISSING;
    const edited: Node = ours.get(key) ?? MISSING;
    const current: Node = theirs.get(key) ?? MISSING;
    if (prior === MISSING) {
      if (edited === MISSING) {
        if (current !== MISSING) merged.set(key, clone(current as Record<string, unknown>));
      } else if (current === MISSING) {
        merged.set(key, clone(edited as Record<string, unknown>));
      } else {
        const value = mergeNode([...path, key], prior, edited, current, conflicts);
        if (value !== MISSING) merged.set(key, value as Record<string, unknown>);
      }
      continue;
    }
    if (edited === MISSING || current === MISSING) {
      if (edited === MISSING && current === MISSING) continue;
      const remaining = edited === MISSING ? current : edited;
      if (equal(remaining, prior)) continue;
      conflicts.push(`${pathText([...path, key])}: delete/edit`);
      if (edited !== MISSING) merged.set(key, clone(edited as Record<string, unknown>));
      continue;
    }
    const value = mergeNode([...path, key], prior, edited, current, conflicts);
    if (value !== MISSING) merged.set(key, value as Record<string, unknown>);
  }

  const keys = (value: Node) => (value === MISSING ? [] : value as Record<string, unknown>[])
    .map((row) => spec.key(row))
    .filter((key): key is string => !!key && merged.has(key));
  const beforeOrder = keys(base);
  const localOrder = keys(local);
  const remoteOrder = keys(remote);
  const baseSurvivors = beforeOrder.filter((key) => merged.has(key));
  const sameOrder = (left: string[], right: string[]) => left.length === right.length && left.every((key, index) => key === right[index]);
  const localBaseOrder = localOrder.filter((key) => before.has(key));
  const remoteBaseOrder = remoteOrder.filter((key) => before.has(key));
  let order = remoteOrder;
  if (sameOrder(remoteBaseOrder, baseSurvivors) && !sameOrder(localBaseOrder, baseSurvivors)) {
    order = [...localOrder, ...remoteOrder.filter((key) => !localOrder.includes(key))];
  } else if (!sameOrder(remoteBaseOrder, baseSurvivors) && !sameOrder(localBaseOrder, baseSurvivors) && !sameOrder(localBaseOrder, remoteBaseOrder)) {
    conflicts.push(`${pathText(path)}: order`);
  }
  for (const key of merged.keys()) if (!order.includes(key)) order.push(key);
  return order.map((key) => merged.get(key)!);
}

function mergeNode(path: string[], base: Node, local: Node, remote: Node, conflicts: string[]): Node {
  if (path.length === 1 && path[0] === "assets") return remote === MISSING ? [] : clone(remote);
  if (Array.isArray(base) || Array.isArray(local) || Array.isArray(remote)) return mergeArray(path, base, local, remote, conflicts);
  if (equal(local, base)) return remote === MISSING ? MISSING : clone(remote);
  if (equal(remote, base) || equal(local, remote)) return local === MISSING ? MISSING : clone(local);
  if (local === MISSING || remote === MISSING) {
    conflicts.push(pathText(path));
    return local;
  }
  if (base && local && remote && typeof base === "object" && typeof local === "object" && typeof remote === "object") {
    const value: Record<string, unknown> = {};
    const keys = new Set([...Object.keys(base as Record<string, unknown>), ...Object.keys(local as Record<string, unknown>), ...Object.keys(remote as Record<string, unknown>)]);
    for (const key of keys) {
      const merged = mergeNode(
        [...path, key],
        property(base as Record<string, unknown>, key),
        property(local as Record<string, unknown>, key),
        property(remote as Record<string, unknown>, key),
        conflicts,
      );
      if (merged !== MISSING) value[key] = merged;
    }
    return value;
  }
  conflicts.push(pathText(path));
  return clone(local);
}

function assetReferenceConflicts(document: MapsDocument, remote: MapsDocument): string[] {
  const assetIds = new Set(remote.assets.map((asset) => asset.id));
  const conflicts: string[] = [];
  const check = (churches: MapsDocument["slides"][number]["churches"], path: string) => churches.forEach((church, index) => {
    if (church.assetId && !assetIds.has(church.assetId)) conflicts.push(`${path}.${index}.assetId`);
  });
  document.slides.forEach((slide, index) => {
    check(slide.churches, `slides.${index}.churches`);
    if (slide.cg) check(slide.cg.churches, `slides.${index}.cg.churches`);
  });
  return conflicts;
}

export function threeWay<T extends Record<string, unknown>>(base: T, local: T, remote: T): RebaseResult<T> {
  const conflicts: string[] = [];
  validateKeyedShape(base, [], conflicts);
  validateKeyedShape(local, [], conflicts);
  validateKeyedShape(remote, [], conflicts);
  const value = mergeNode([], base, local, remote, conflicts);
  return { value: value as T, conflicts };
}

export function rebaseMapsDocument(base: MapsDocument, local: MapsDocument, remote: MapsDocument): RebaseResult<MapsDocument> {
  const result = threeWay(base, local, remote);
  result.value.assets = clone(remote.assets || []);
  result.conflicts.push(...assetReferenceConflicts(result.value, remote));
  return result;
}
