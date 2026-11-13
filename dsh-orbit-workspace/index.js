export function apply(ctx) {
  ctx.effect(() => () => {}, "dsh-orbit-workspace: host lifecycle");
}
