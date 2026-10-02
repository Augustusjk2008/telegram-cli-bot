`include "../include/core.svh"

module system(input clk);
    core #(.WIDTH(8)) u_core (.clk(clk));
`ifdef EXTRA_CORE
    core u_optional (.clk(clk));
`endif
endmodule
