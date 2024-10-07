from flask import Flask, render_template, request, redirect, make_response  # make_response burada import edildi
import sqlite3
from datetime import datetime
import csv
from io import StringIO
app = Flask(__name__)

# Veritabanı bağlantısı ve tabloların oluşturulması
def connect_db():
    conn = sqlite3.connect('budget.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect_db() as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            description TEXT,
            amount REAL,
            date TEXT
        )''')
        conn.execute('''
        CREATE TABLE IF NOT EXISTS balance (
            id INTEGER PRIMARY KEY,
            total REAL DEFAULT 0
        )''')
        if conn.execute('SELECT COUNT(*) FROM balance').fetchone()[0] == 0:
            conn.execute('INSERT INTO balance (id, total) VALUES (1, 0)')
        conn.commit()

@app.route('/')
def index():
    conn = connect_db()
    transactions = conn.execute('SELECT * FROM transactions ORDER BY date DESC LIMIT 10').fetchall()
    balance = conn.execute('SELECT total FROM balance WHERE id = 1').fetchone()['total']
    conn.close()
    
    formatted_transactions = [{
        'description': txn['description'],
        'amount': "{:+,.2f}".format(float(txn['amount'])),
        'date': datetime.strptime(txn['date'], '%Y-%m-%d').strftime('%B %d, %Y'),
        'class': 'positive' if txn['amount'] >= 0 else 'negative'
    } for txn in transactions]
    
    return render_template('index.html', balance="{:,.2f}".format(balance), transactions=formatted_transactions)

# Anapara ekleme
@app.route('/add_funds', methods=['POST'])
def add_funds():
    description = request.form['description']
    amount = float(request.form['amount'])
    date = request.form['date']

    conn = connect_db()
    conn.execute('INSERT INTO transactions (description, amount, date) VALUES (?, ?, ?)', (description, amount, date))
    conn.execute('UPDATE balance SET total = total + ? WHERE id = 1', (amount,))
    conn.commit()
    conn.close()
    return redirect('/')

# Harcama ekleme (miktar negatif olarak kaydedilir)
@app.route('/add_expense', methods=['POST'])
def add_expense():
    description = request.form['description']
    amount = -abs(float(request.form['amount']))  # Harcama her zaman negatif kaydedilir
    date = request.form['date']

    conn = connect_db()
    conn.execute('INSERT INTO transactions (description, amount, date) VALUES (?, ?, ?)', (description, amount, date))
    conn.execute('UPDATE balance SET total = total + ? WHERE id = 1', (amount,))
    conn.commit()
    conn.close()
    return redirect('/')
# CSV Dışa Aktarma İşlevi (Her sütuna ayrı ayrı yazacak şekilde)
@app.route('/export_csv')
def export_csv():
    conn = connect_db()
    transactions = conn.execute('SELECT * FROM transactions ORDER BY date DESC').fetchall()
    conn.close()

    si = StringIO()
    cw = csv.writer(si)

    # UTF-8 ile BOM eklemek (Excel'de Türkçe karakterlerin doğru görüntülenmesi için)
    si.write('\ufeff')

    # CSV Başlıkları (ID, Açıklama, Miktar, Tarih)
    cw.writerow(['ID', 'Açıklama', 'Miktar (TL)', 'Tarih'])

    # Her işlemi ayrı sütunlara yaz
    for txn in transactions:
        formatted_amount = "{:+,.2f}".format(float(txn['amount']))  # Miktarı iki ondalık basamakla formatla
        formatted_date = datetime.strptime(txn['date'], '%Y-%m-%d').strftime('%d-%m-%Y')  # Tarihi dd-mm-yyyy formatına çevir
        cw.writerow([txn['id'], txn['description'], formatted_amount, formatted_date])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=transactions.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
