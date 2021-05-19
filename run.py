import requests
import time
import random
import json 
import os

from flask import Flask
from flask import request, render_template, send_file
from flask import jsonify
from flask_socketio import SocketIO
from flask_apscheduler import APScheduler

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.DEBUG)
async_mode = None

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode=async_mode)

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

url = os.environ.get('RPC_URL', 'http://localhost:7076')
update_time = int(os.environ.get('UPDATE_TIME', '5'))
conf_active = {'action' : 'confirmation_active'}

elections_list = []
hash_dict = {}
broadcast_data = []

peer_ip = {}
rep_conf = {}
rep_cemented = {}

# read file
with open('aliases.json', 'r') as myfile:
    data=myfile.read()

# parse file
rep_json = json.loads(data)
rep_dict = {}
for rep in rep_json:
    print(rep)
    account = rep['account']
    rep_dict[account] = rep['alias']

@scheduler.task('interval', id='do_job_1', seconds=update_time, misfire_grace_time=900)

def scheduled_task():
    print('SCHEDULE: Start')
    with scheduler.app.app_context():
        confirmation_quorum_command = {'action' : 'confirmation_quorum', 'peer_details': 'true'}
        x = requests.post(url, json = confirmation_quorum_command)
        confirmation_quorum_result = x.json()

        for peers in confirmation_quorum_result['peers']:
            ip_parts = str(peers['ip']).split(']')
            ip_address = ip_parts[0][1:]
#            print('{} : {}'.format(ip_address, peers['account']))
            peer_ip[ip_address] = peers['account']

        x = requests.post(url, json = conf_active)
        result = x.json()
        confs = result['confirmations']
        total_confs = int(result['unconfirmed'])

        while len(elections_list) < 20:
            random_conf = random.randrange(total_confs)
            elections_list.append(confs[random_conf])
            hash_dict[confs[random_conf]] = '0'

        broadcast_data.clear()
        for election in elections_list:
            if election not in confs:
                if election in hash_dict:
                    block_info = {'action' : 'block_info', 'json_block': 'true', 'hash': hash_dict[election] }
                    x = requests.post(url, json = block_info)
                    result = x.json()
                    print(result)
                    if 'confirmed' in result:
                        confirmed = result['confirmed']
                    else:
                        confirmed = 'false'
                    print(confirmed)
                    print()
                    if confirmed == 'false':
                        print('Dropping')
                        broadcast_data.append({ 'root' : election, 'hash' : hash_dict[election], 'tally' : '600000000' , 'rep_num' : '0' , 'status' : 'DROPPED'})
                    else:
                        print('Success')
                        broadcast_data.append({ 'root' : election, 'hash' : hash_dict[election], 'tally' : '600000000' , 'rep_num' : '0' , 'status' : 'SUCCESSFUL'})


                print('Removing election')
                elections_list.remove(election)

                if election in hash_dict:
                    del hash_dict[election]

            else:
                conf_command = {'action' : 'confirmation_info', 'json_block': 'true', 'root': election , 'representatives': 'true' }

                x = requests.post(url, json = conf_command)
                result = x.json()
#                print(result)
                total_tally = result['total_tally']
                last_winner = result['last_winner']
                representatives = result['blocks'][last_winner]['representatives']

                hash_dict[election] = last_winner
#                print('Winner: {}, Tally: {}'.format(last_winner, total_tally))
#            broadcast_data[last_winner] =  total_tally
                broadcast_data.append({ 'root' : election, 'hash' : last_winner, 'tally' : total_tally, 'rep_num' : len(representatives), 'status' : 'IN_PROGRESS'})

        broadcast_json = json.dumps(broadcast_data)
#        print(broadcast_json)
#        socketio.emit('update',{'data' : 'test'} , broadcast=True)
        print('SCHEDULE: Done')
        socketio.emit('update', broadcast_json , broadcast=True)

@socketio.on('connect')
def test_connect():
    print('connected')
    socketio.emit('my response', {'data': 'Connected'})

@app.route('/')
def start_page():
    return send_file('./templates/index.html')

@app.route('/conf/random')
def start():

    x = requests.post(url, json = conf_active)
    result = x.json()
    confs = result['confirmations']
    total_confs = int(result['unconfirmed'])
    print(total_confs)
    print('Last Conf: {}'.format(confs[-1]))
    random_conf = random.randrange(total_confs)
    return '<html><h1>Conf Monitor</h1><br>Here is a random election to monitor:<br><a href="https://nanostatus.live/conf/{}">{}</a></html>'.format(confs[random_conf], confs[random_conf])


@app.route('/conf/all')
def all_elections():
    x = requests.post(url, json = conf_active)
    result = x.json()
    confs = result['confirmations']
    total_confs = int(result['unconfirmed'])
    all =[]
    for root in confs:
        conf_command = {'action' : 'confirmation_info', 'json_block': 'true', 'root': root ,'representatives': 'true'}
        x = requests.post(url, json = conf_command)
        result = x.json()
        if 'total_tally' in result:
            total_tally = result['total_tally']
            last_winner = result['last_winner']

            all.append('{} {}<br>'.format(last_winner, total_tally))
    return str(all)

@app.route('/conf/random/json')
def start_json():

    x = requests.post(url, json = conf_active)
    result = x.json()
    confs = result['confirmations']
    total_confs = int(result['unconfirmed'])
    print(total_confs)
    print('Last Conf: {}'.format(confs[-1]))
    random_conf = random.randrange(total_confs)
    return jsonify(confs[random_conf])

@app.route('/conf/<string:root>')
def conf_info(root):

    print('{} {}'.format(len(peer_ip), len(rep_conf)))
    rep_command = {'action' : 'telemetry', 'raw': 'true'}
    x = requests.post(url, json = rep_command)
    rep_result = x.json()

    for nodes in rep_result['metrics']:
        try:
#            if nodes['address'] in peer_ip:
#                print('Found address')
#            else:
#                print('Not present')

            node_address = peer_ip[nodes['address']]
            node_version = nodes['major_version']
            node_cemented_count = nodes['cemented_count']
            rep_conf[node_address] = node_version
            rep_cemented[node_address] = node_cemented_count
        except:
     #       print('Failed: {}'.format(nodes))
            pass

    conf_command = {'action' : 'confirmation_info', 'json_block': 'true', 'root': root ,'representatives': 'true'}

    x = requests.post(url, json = conf_command)
    result = x.json()

    if 'total_tally' in result:
        total_tally = result['total_tally']
    else:
        return '<html><head><meta http-equiv="refresh" content="5"></head>Election completed or dropped</html>'

    last_winner = result['last_winner']
    representatives = result['blocks'][last_winner]['representatives']

    representatives_list = '<table><tr><th>Rep</th><th>Weight</th><th>Name</th><th>Node Version</th><th>Cemented</th></tr>'

    balance = result['blocks'][last_winner]['contents']['balance']
    account = result['blocks'][last_winner]['contents']['account']

    for reps in representatives:

        try:
            name = rep_dict[reps]
        except:
            name = 'None'

        try:
            node_version = rep_conf[reps]
        except:
            node_version = 'failed'

        try:
            node_cemented = rep_cemented[reps]
        except:
            node_cemented = 'failed'

        representatives_list = '{}<tr><td>{}</td><td>{} Nano</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(representatives_list, reps, int(int(representatives[reps]) / 1000000000000000000000000000000), name, node_version, node_cemented)

    return '<html><head><meta http-equiv="refresh" content="5"></head>Last Winner: {}<br> Total Tally: {}<br>Account: {}<br>Block Balance: {}<br><br>{}</table></html>'.format(last_winner, total_tally, account, balance, representatives_list)


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0')
