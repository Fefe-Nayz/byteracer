export default function AxisValue({ value }: { value: number }) {
  return (
    <div>
      <progress max={2} value={value + 1} />
    </div>
  );
}
