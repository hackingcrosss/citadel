from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp


@api_bp.route('/website-generator/generate', methods=['POST'])
@login_required
def website_generator_generate():
    data = request.get_json() or {}
    category = data.get('category', '').strip()
    if not category:
        return jsonify({'error': 'category is required'}), 400

    from app.tasks.website_generator_tasks import generate_website_task
    from app.services import task_log_service
    task = generate_website_task.delay(category)
    task_log_service.log_task(task.id, 'website_generation', category)
    return jsonify({'task_id': task.id})


@api_bp.route('/website-generator/status/<task_id>', methods=['GET'])
@login_required
def website_generator_status(task_id):
    from app.tasks.celery_app import celery
    result = celery.AsyncResult(task_id)

    response = {'task_id': task_id, 'status': result.status}
    if result.status == 'SUCCESS':
        response['result'] = result.result
    elif result.status == 'FAILURE':
        response['error'] = str(result.result)
    return jsonify(response)


@api_bp.route('/website-generator/deploy', methods=['POST'])
@login_required
def website_generator_deploy():
    data = request.get_json() or {}
    html = data.get('html', '').strip()
    category = data.get('category', '').strip()
    if not html:
        return jsonify({'error': 'html is required'}), 400
    if not category:
        return jsonify({'error': 'category is required'}), 400

    try:
        from app.services import website_generator_service
        result = website_generator_service.deploy_website(html, category)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/website-generator/relaunch', methods=['POST'])
@login_required
def website_generator_relaunch():
    try:
        from app.services import website_generator_service
        result = website_generator_service.relaunch_containers()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/website-generator/publish', methods=['POST'])
@login_required
def website_generator_publish():
    data = request.get_json() or {}
    html = data.get('html', '').strip()
    category = data.get('category', '').strip()
    zone_id = data.get('zone_id', '').strip()
    zone_name = data.get('zone_name', '').strip()
    subdomain = data.get('subdomain', '').strip()

    if not html:
        return jsonify({'error': 'html is required'}), 400
    if not category:
        return jsonify({'error': 'category is required'}), 400
    if not zone_id or not zone_name:
        return jsonify({'error': 'zone_id and zone_name are required'}), 400

    try:
        from app.services import website_generator_service
        result = website_generator_service.publish_website(
            html=html,
            category=category,
            zone_id=zone_id,
            zone_name=zone_name,
            subdomain=subdomain,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
