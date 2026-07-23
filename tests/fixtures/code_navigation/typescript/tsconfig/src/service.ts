import type { Greeter } from "./contracts";

export class ConcreteGreeter implements Greeter {
  greet(name: string): string {
    return `Hello, ${name}`;
  }
}
