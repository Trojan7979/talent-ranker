import { useRecruiterSession } from "./RecruiterLayout";

export function RecruiterTokenField() {
  const { email } = useRecruiterSession();
  return <span>Signed in as {email}</span>;
}
