_base_ = ['./base_static.py']

ir_config = dict(output_names=['dets', 'labels', 'masks'])
codebase_config = dict(post_processing=dict(export_postprocess_mask=False))
