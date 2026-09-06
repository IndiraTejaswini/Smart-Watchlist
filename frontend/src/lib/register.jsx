import { createContext, useContext } from "react";

/**
 * register.jsx — FRONTEND_SPEC §1.2, expressed as a runtime constraint rather
 * than a house rule.
 *
 * The app runs in one dark environment but shifts *register* between two kinds
 * of surface. The Terminal shows the market as it is: green and red carry price
 * direction. The Dispatch — the Brief — shows what a careful reader concluded:
 * no green, no red, direction by geometry, colour reserved for data confidence.
 *
 * That distinction is the product's whole thesis, so it should not depend on a
 * developer remembering it at every call site. A component tree wrapped in
 * `<Register value="dispatch">` cannot emit a directional colour: `Num` asks
 * this context before it resolves a tone, and downgrades to neutral if the
 * surface forbids it. The rule is enforced by the place it applies to, which is
 * the only kind of rule that survives contact with a deadline.
 */

const RegisterContext = createContext("terminal");

/** @param {{ value: "terminal"|"dispatch", children: React.ReactNode }} props */
export function Register({ value, children }) {
  return (
    <RegisterContext.Provider value={value}>
      {children}
    </RegisterContext.Provider>
  );
}

/** @returns {"terminal"|"dispatch"} */
export function useRegister() {
  return useContext(RegisterContext);
}

/** True when the current surface is allowed to colour by price direction. */
export function useAllowsDirectionColour() {
  return useContext(RegisterContext) === "terminal";
}
