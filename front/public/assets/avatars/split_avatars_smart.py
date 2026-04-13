from PIL import Image
import numpy as np
import os

def find_uniform_regions(img_array, axis, expected_count):
    """
    通过分析颜色均匀性来找到网格线
    假设每个头像区域内部颜色相对均匀，边界处颜色变化大
    """
    height, width = img_array.shape[:2]

    if axis == 0:  # 水平方向 - 分析行
        # 计算每行的颜色标准差（衡量颜色变化）
        row_std = np.std(img_array, axis=(1, 2))

        # 找到标准差较低的区域（均匀区域）
        # 边界处标准差会较高
        threshold = np.mean(row_std) * 0.5

        # 找到可能是边界的行（标准差较高的位置）
        boundary_candidates = []
        for i in range(1, len(row_std) - 1):
            if row_std[i] > threshold and (row_std[i-1] < threshold or row_std[i+1] < threshold):
                boundary_candidates.append(i)

        # 如果没有找到足够的边界，使用等分
        if len(boundary_candidates) < expected_count - 1:
            step = height // expected_count
            return [i * step for i in range(expected_count + 1)]

        # 对边界候选进行聚类，选择最接近等分位置的
        expected_positions = [int(height * i / expected_count) for i in range(1, expected_count)]

        selected_boundaries = []
        for expected in expected_positions:
            # 找到最接近期望位置的边界
            closest = min(boundary_candidates, key=lambda x: abs(x - expected))
            selected_boundaries.append(closest)

        return [0] + sorted(selected_boundaries) + [height]

    else:  # 垂直方向 - 分析列
        col_std = np.std(img_array, axis=(0, 2))
        threshold = np.mean(col_std) * 0.5

        boundary_candidates = []
        for i in range(1, len(col_std) - 1):
            if col_std[i] > threshold and (col_std[i-1] < threshold or col_std[i+1] < threshold):
                boundary_candidates.append(i)

        if len(boundary_candidates) < expected_count - 1:
            step = width // expected_count
            return [i * step for i in range(expected_count + 1)]

        expected_positions = [int(width * i / expected_count) for i in range(1, expected_count)]

        selected_boundaries = []
        for expected in expected_positions:
            closest = min(boundary_candidates, key=lambda x: abs(x - expected))
            selected_boundaries.append(closest)

        return [0] + sorted(selected_boundaries) + [width]

def find_grid_by_color_clusters(img_array, rows, cols):
    """
    使用颜色聚类来找到网格线
    通过检测背景色块之间的边界
    """
    height, width = img_array.shape[:2]

    # 简化颜色 - 量化到较少的颜色级别
    quantized = (img_array // 32) * 32

    # 水平方向：分析每一行的主要颜色
    h_boundaries = []
    expected_h = [int(height * i / rows) for i in range(1, rows)]

    for expected in expected_h:
        # 在期望位置附近搜索
        search_start = max(0, expected - 50)
        search_end = min(height, expected + 50)

        best_boundary = expected
        max_color_diff = 0

        for y in range(search_start + 1, search_end):
            # 计算相邻行的颜色差异
            diff = np.mean(np.abs(quantized[y].astype(float) - quantized[y-1].astype(float)))
            if diff > max_color_diff:
                max_color_diff = diff
                best_boundary = y

        h_boundaries.append(best_boundary)

    # 垂直方向
    v_boundaries = []
    expected_v = [int(width * i / cols) for i in range(1, cols)]

    for expected in expected_v:
        search_start = max(0, expected - 50)
        search_end = min(width, expected + 50)

        best_boundary = expected
        max_color_diff = 0

        for x in range(search_start + 1, search_end):
            diff = np.mean(np.abs(quantized[:, x].astype(float) - quantized[:, x-1].astype(float)))
            if diff > max_color_diff:
                max_color_diff = diff
                best_boundary = x

        v_boundaries.append(best_boundary)

    h_lines = [0] + sorted(h_boundaries) + [height]
    v_lines = [0] + sorted(v_boundaries) + [width]

    return h_lines, v_lines

def smart_split_avatars_v2(input_file, output_dir=".", target_size=(64, 64)):
    """
    智能分割头像 V2 - 使用颜色聚类方法
    """
    # 打开图片
    img = Image.open(input_file)
    if img.mode != 'RGB':
        img = img.convert('RGB')

    img_array = np.array(img)
    height, width = img_array.shape[:2]

    print(f"图片尺寸: {width}x{height}")
    print("使用颜色聚类方法检测网格线...")

    # 检测网格线 (4列 x 3行)
    h_lines, v_lines = find_grid_by_color_clusters(img_array, rows=3, cols=4)

    print(f"水平分割线: {h_lines}")
    print(f"垂直分割线: {v_lines}")

    # 验证分割数量
    if len(h_lines) != 4 or len(v_lines) != 5:
        print(f"警告: 检测到 {len(h_lines)-1}x{len(v_lines)-1} 网格，期望 3x4")

    # 分割并保存头像
    avatar_index = 1
    for row in range(len(h_lines) - 1):
        for col in range(len(v_lines) - 1):
            upper = h_lines[row]
            lower = h_lines[row + 1]
            left = v_lines[col]
            right = v_lines[col + 1]

            # 裁剪头像
            avatar = img.crop((left, upper, right, lower))

            # 调整大小
            avatar = avatar.resize(target_size, Image.Resampling.LANCZOS)

            # 保存
            output_file = os.path.join(output_dir, f"avatar_{avatar_index:02d}.png")
            avatar.save(output_file, "PNG")
            print(f"已保存: {output_file} (原尺寸: {right-left}x{lower-upper})")

            avatar_index += 1

    print(f"\n完成！共分割出 {avatar_index - 1} 个头像")
    return h_lines, v_lines

if __name__ == "__main__":
    smart_split_avatars_v2("whole.png", ".", target_size=(64, 64))
