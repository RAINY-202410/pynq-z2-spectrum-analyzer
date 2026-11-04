# PYNQ Overlay Bring-up Checklist

- [ ] Stop old service; confirm the target port is free.
- [ ] Record board, kernel, PYNQ, XRT, Python, and NumPy versions.
- [ ] Hash `bit` and `hwh`; verify they are one matching pair.
- [ ] Confirm the overlay metadata contains the expected IP names/addresses.
- [ ] Read a protocol ID or scratch register before starting DMA.
- [ ] Confirm DMA direction, transfer length, stream width, and alignment.
- [ ] Set a bounded timeout for every DMA operation.
- [ ] Save raw input and raw output before plotting or normalization.
- [ ] Compare against a frozen golden model and report the first mismatch.
- [ ] Exercise busy/start/abort/clear/overflow error paths.
- [ ] Stop DMA, drop buffers, close the overlay, and confirm the port is free.
- [ ] Repeat after a real power cycle at least three times when stability matters.
- [ ] Label host, simulation, smoke, long-run, and final acceptance separately.
