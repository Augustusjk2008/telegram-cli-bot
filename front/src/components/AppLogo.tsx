import { clsx } from "clsx";
import { APP_NAME } from "../theme";

export const APP_LOGO_SRC = "/assets/app-logo.svg";
export const APP_LOGO_CLASSIC_SRC = "/assets/app-logo-classic.svg";

type Props = {
  size?: number;
  className?: string;
  imgClassName?: string;
  decorative?: boolean;
};

export function AppLogo({
  size = 32,
  className,
  imgClassName,
  decorative = false,
}: Props) {
  return (
    <span
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : `${APP_NAME} logo`}
      aria-hidden={decorative ? "true" : undefined}
      className={clsx("app-logo inline-flex shrink-0 items-center justify-center", className)}
      style={{ width: size, height: size }}
    >
      <img
        src={APP_LOGO_SRC}
        alt=""
        aria-hidden="true"
        className={clsx("app-logo-image app-logo-image--deep h-full w-full object-contain", imgClassName)}
        draggable={false}
      />
      <img
        src={APP_LOGO_CLASSIC_SRC}
        alt=""
        aria-hidden="true"
        className={clsx("app-logo-image app-logo-image--classic h-full w-full object-contain", imgClassName)}
        draggable={false}
      />
    </span>
  );
}
