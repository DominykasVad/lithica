import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// what one test rendered is gone before the next
afterEach(cleanup);
