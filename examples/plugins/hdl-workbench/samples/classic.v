/* module phantom; endmodule */
module classic(a, b, result, clk);
    input [7:0] a, b;
    input clk;
    output result;
    reg [8:0] result;
    parameter WIDTH = 8;
    child u_child (.a(a), .clk(clk));
endmodule
