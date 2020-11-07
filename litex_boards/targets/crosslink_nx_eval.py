#!/usr/bin/env python3

# This file is Copyright (c) 2018-2019 Florent Kermarrec <florent@enjoy-digital.fr>
# This file is Copyright (c) 2018-2019 David Shah <dave@ds0.me>
# License: BSD

import os
import argparse

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from litex_boards.platforms import crosslink_nx_eval

from litex.soc.cores.nexuslram import NexusLRAM
from litex.soc.cores.spi_flash import SpiFlash
from litex.build.io import CRG
from litex.build.generic_platform import *

from litex.soc.cores.clock import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.led import LedChaser

kB = 1024
mB = 1024*kB


# CRG ----------------------------------------------------------------------------------------------

class _CRG(Module):
    def __init__(self, platform, sys_clk_freq):
        self.clock_domains.cd_por = ClockDomain()
        self.clock_domains.cd_sys = ClockDomain()

        # Built in OSC
        self.submodules.hf_clk = NexusOSCA()
        hf_clk_freq = 25e6
        self.hf_clk.create_hf_clk(self.cd_por, hf_clk_freq)

        # Power on reset
        por_count = Signal(16, reset=2**16-1)
        por_done  = Signal()
        self.comb += por_done.eq(por_count == 0)
        self.sync.por += If(~por_done, por_count.eq(por_count - 1))

        self.rst_n = platform.request("gsrn")
        self.specials += AsyncResetSynchronizer(self.cd_por, ~self.rst_n)

        # PLL
        self.submodules.sys_pll = sys_pll = NEXUSPLL()
        sys_pll.register_clkin(self.cd_por.clk, hf_clk_freq)
        sys_pll.create_clkout(self.cd_sys, sys_clk_freq)
        self.specials += AsyncResetSynchronizer(self.cd_sys, ~self.sys_pll.locked |  ~por_done )

        # This really shouldn't be necessary but the Lattice tools seem to do some weird timing things with latency around
        # generated clocks and I haven't received any answers from Lattice about the details of what it's doing and why.
        platform.add_period_constraint(self.cd_sys.clk, 1e9/sys_clk_freq)


# BaseSoC ------------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    SoCCore.mem_map = {
        "rom":              0x00000000,
        "sram":             0x40000000,
        "csr":              0xf0000000,
    }
    def __init__(self, sys_clk_freq, **kwargs):
        platform = crosslink_nx_eval.Platform()

        platform.add_platform_command("ldc_set_sysconfig {{MASTER_SPI_PORT=SERIAL}}")

        # Disable Integrated SRAM since we want to instantiate LRAM specifically for it
        kwargs["integrated_sram_size"] = 0

        # Make serial_pmods available 
        platform.add_extension(crosslink_nx_eval.serial_pmods)

        # SoCCore -----------------------------------------_----------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq,
            ident          = "LiteX SoC on Crosslink-NX Evaluation Board",
            ident_version  = True,
            **kwargs)

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = _CRG(platform, sys_clk_freq)

        # 128KB LRAM (used as SRAM) ---------------------------------------------------------------
        size = 128*kB
        self.submodules.spram = NexusLRAM(32, size)
        self.register_mem("sram", self.mem_map["sram"], self.spram.bus, size)

        # Leds -------------------------------------------------------------------------------------
        self.submodules.leds = LedChaser(
            pads         = Cat(*[platform.request("user_led", i) for i in range(14)]),
            sys_clk_freq = sys_clk_freq)
        self.add_csr("leds")


# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteX SoC on Crosslink-NX Eval Board")
    parser.add_argument("--build", action="store_true", help="Build bitstream")
    parser.add_argument("--load", action="store_true", help="Load bitstream")
    parser.add_argument("--sys-clk-freq",  default=75e6, help="System clock frequency (default=75MHz)")
    parser.add_argument("--serial",  default="serial", help="UART Pins: serial or serial_pmod[0-2] (default=serial)")
    parser.add_argument("--prog-target",  default="direct", help="Programming Target: direct or flash")
    builder_args(parser)
    soc_core_args(parser)
    args = parser.parse_args()

    soc = BaseSoC(int(float(args.sys_clk_freq)), **soc_core_argdict(args))
    builder = Builder(soc, **builder_argdict(args))
    builder_kargs = {}
    builder.build(**builder_kargs, run=args.build)

    if args.load:
        prog = soc.platform.create_programmer(args.prog_target)
        prog.load_bitstream(os.path.join(builder.gateware_dir, soc.build_name + ".bit"))

if __name__ == "__main__":
    main()
