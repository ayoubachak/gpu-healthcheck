# Scorecard for a used GPU purchase

Fill this in while standing next to the seller's machine. Keep the serial and invoice
private.

## Identification

- Listing / date:
- Asking price / agreed price:
- Exact board model:
- Serial and purchase date:
- Original invoice available? Yes / No
- Repaired, repasted, mined, or run 24/7? Seller's statement:

## Physical, with power off

- 16-pin socket and cable: OK / DAMAGED (describe)
- Cable fully seated, no bent or discoloured contacts? Yes / No
- Fans spin freely, no play, no unusual noise? Yes / No
- Board, screws, cooler and warranty seals show repairs? Yes / No
- PSU model and wattage used for the test:

## Software evidence

- `nvidia-smi` / GPU-Z identity and 24 GB confirmed? Yes / No
- Stock clocks and power limit? Yes / No
- PCIe link generation and width:
- memtest_vulkan: duration / selected GPU / memory allocated / errors:
- OCCT VRAM: duration / errors:
- OCCT 3D Adaptive: duration / errors:
- gpu-burn final status (FP32 / Tensor):
- Time Spy **Graphics** score:
- Max core temperature, hotspot, memory junction (if readable):
- Power draw and clocks under sustained load:
- Driver resets in Event Viewer or `NVRM: Xid`:
- Seller allows on-site testing and protected payment? Yes / No

## Decision

- Decision: BUY / RETEST / REJECT
- Outstanding risks:

Reject, pending an independent diagnosis, if: the 16-pin connector is damaged, a memory
test reproduces errors on a known-good host, or the card is unstable at stock settings.

Software output can be fabricated. Prefer watching the tests run and checking the card
in person.
