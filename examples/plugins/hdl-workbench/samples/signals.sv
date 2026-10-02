module async_register (
    input logic clk,
    input logic rst_n,
    input logic enable,
    input logic [7:0] data,
    output logic [7:0] value
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            value <= '0;
        else if (enable)
            value <= data;
    end
endmodule

module sync_register (
    input logic clk,
    input logic clear,
    input logic [7:0] data,
    output logic [7:0] value
);
    always @(posedge clk) begin
        if (clear)
            value <= 8'h00;
        else
            value <= data;
    end
endmodule
