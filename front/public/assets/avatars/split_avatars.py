from PIL import Image
import os

# 读取原始图片
input_file = "whole.png"
output_dir = "."

# 打开图片
img = Image.open(input_file)
width, height = img.size

# 计算每个头像的尺寸
# 4列 x 3行，共12个头像
cols = 4
rows = 3

avatar_width = width // cols
avatar_height = height // rows

print(f"图片尺寸: {width}x{height}")
print(f"每个头像尺寸: {avatar_width}x{avatar_height}")

# 分割图片
avatar_index = 1
for row in range(rows):
    for col in range(cols):
        # 计算裁剪区域
        left = col * avatar_width
        upper = row * avatar_height
        right = left + avatar_width
        lower = upper + avatar_height

        # 裁剪头像
        avatar = img.crop((left, upper, right, lower))

        # 调整大小为 64x64（如果需要的话）
        avatar = avatar.resize((64, 64), Image.Resampling.LANCZOS)

        # 保存头像
        output_file = os.path.join(output_dir, f"avatar_{avatar_index:02d}.png")
        avatar.save(output_file, "PNG")
        print(f"已保存: {output_file}")

        avatar_index += 1

print(f"\n完成！共分割出 {avatar_index - 1} 个头像")
