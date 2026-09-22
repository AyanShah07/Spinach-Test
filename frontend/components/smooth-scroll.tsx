"use client";
import { MotionConfig } from "framer-motion";

export function SmoothScroll({ children }: { children: React.ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
