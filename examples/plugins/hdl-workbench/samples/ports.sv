// 中文注释中的 module fake(input bad); endmodule 不属于设计。
module top #(
    parameter int WIDTH = 8, DEPTH = 2,
    parameter type T = logic [WIDTH-1:0]
) (
    input logic signed [WIDTH-1:0] a,
                                 b,
    input clk,
    output reg [WIDTH:0] result,
    output T data [DEPTH]
);
    localparam integer OFFSET = 1, LAST = WIDTH - 1;
    child #(.WIDTH(WIDTH), .DEPTH(DEPTH))
        u_named (.clk(clk), .a(a), .result(), .*),
        u_second (.clk(clk), .a(b));
    child #(WIDTH, DEPTH) u_positional (clk, , {a, b});
endmodule

module child #(
    parameter WIDTH = 4,
    parameter DEPTH = 1
) (
    input clk,
    input [WIDTH-1:0] a,
    output [WIDTH:0] result
);
endmodule
