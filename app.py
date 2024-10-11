from flask import Flask, render_template, request, redirect, make_response, flash
import sqlite3
from datetime import datetime
import csv
from io import StringIO
import locale

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Flash mesajları için bir gizli anahtar gerekli

# Türkçe tarih formatı için locale ayarı
locale.setlocale(locale.LC_TIME, 'tr_TR.UTF-8')

# Veritabanı bağlantısı ve tabloların oluşturulması
def connect_db():
    conn = sqlite3.connect('budget.db')
    conn.row_factory = sqlite3.Row
    return conn

# Veritabanını başlatma ve tabloları oluşturma
def init_db():
    with connect_db() as conn:
        # Harcamalar için transactions tablosu
        conn.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            description TEXT,
            amount REAL,
            date TEXT,
            type_id INTEGER,
            FOREIGN KEY(type_id) REFERENCES expense_types(id)
        )''')

        # Harcama türlerini eklemek için expense_types tablosu
        conn.execute('''
        CREATE TABLE IF NOT EXISTS expense_types (
            id INTEGER PRIMARY KEY,
            type_name TEXT UNIQUE
        )''')

        # Bakiyeyi tutmak için balance tablosu
        conn.execute('''
        CREATE TABLE IF NOT EXISTS balance (
            id INTEGER PRIMARY KEY,
            total REAL DEFAULT 0
        )''')

        # Varsayılan bir bakiye kaydı oluştur
        if conn.execute('SELECT COUNT(*) FROM balance').fetchone()[0] == 0:
            conn.execute('INSERT INTO balance (id, total) VALUES (1, 0)')
        
        conn.commit()

# Ana sayfa, işlemleri ve harcama türlerini gösterir
@app.route('/', methods=['GET', 'POST'])
def index():
    conn = connect_db()

    if request.method == 'POST':
        # Yeni harcama türü ekleme
        if 'new_type_name' in request.form:
            type_name = request.form['new_type_name']
            # Harcama türü daha önce eklenmiş mi kontrol et
            existing_type = conn.execute('SELECT * FROM expense_types WHERE type_name = ?', (type_name,)).fetchone()
            if existing_type:
                flash('Bu harcama türü zaten mevcut!', 'error')  # Hata mesajı
            else:
                conn.execute('INSERT INTO expense_types (type_name) VALUES (?)', (type_name,))
                conn.commit()
                flash('Harcama türü başarıyla eklendi!', 'success')  # Başarı mesajı

    # Tüm harcama türlerini ve son işlemleri getir
    types = conn.execute('SELECT * FROM expense_types').fetchall()
    transactions = conn.execute('''
        SELECT t.*, e.type_name 
        FROM transactions t
        LEFT JOIN expense_types e ON t.type_id = e.id
        ORDER BY t.date DESC LIMIT 10
    ''').fetchall()  # İşlemleri ve harcama türlerini birleştirerek getiriyoruz.
    balance = conn.execute('SELECT total FROM balance WHERE id = 1').fetchone()['total']
    
    conn.close()

    formatted_transactions = [{
        'id': txn['id'],
        'description': txn['description'],
        'amount': "{:+,.2f}".format(float(txn['amount'])),
        'date': datetime.strptime(txn['date'], '%Y-%m-%d').strftime('%d %B %Y'),
        'type_name': txn['type_name'],  # Harcama türü ismi
        'class': 'positive' if txn['amount'] >= 0 else 'negative'
    } for txn in transactions]

    return render_template('index.html', balance="{:,.2f}".format(balance), transactions=formatted_transactions, types=types)

# Harcama türlerini silme işlemi
@app.route('/delete_expense_type', methods=['POST'])
def delete_expense_type():
    conn = connect_db()
    type_id = request.form['type_id']
    conn.execute('DELETE FROM expense_types WHERE id = ?', (type_id,))
    conn.commit()
    conn.close()
    flash('Harcama türü başarıyla silindi!', 'success')
    return redirect('/')

# Anapara ekleme
@app.route('/add_funds', methods=['POST'])
def add_funds():
    description = request.form['description']
    amount = float(request.form['amount'])
    date = request.form['date']
    type_id = request.form['type_id']  # Seçilen harcama türü

    conn = connect_db()
    conn.execute('INSERT INTO transactions (description, amount, date, type_id) VALUES (?, ?, ?, ?)', (description, amount, date, type_id))
    conn.execute('UPDATE balance SET total = total + ? WHERE id = 1', (amount,))
    conn.commit()
    conn.close()
    
    return redirect('/')

# Harcama ekleme
@app.route('/add_expense', methods=['POST'])
def add_expense():
    description = request.form['description']
    amount = -abs(float(request.form['amount']))  # Harcama her zaman negatif kaydedilir
    date = request.form['date']
    type_id = request.form['type_id']  # Seçilen harcama türü

    conn = connect_db()
    conn.execute('INSERT INTO transactions (description, amount, date, type_id) VALUES (?, ?, ?, ?)', (description, amount, date, type_id))
    conn.execute('UPDATE balance SET total = total + ? WHERE id = 1', (amount,))
    conn.commit()
    conn.close()
    
    return redirect('/')

# CSV Dışa Aktarma İşlevi
@app.route('/export_csv')
def export_csv():
    conn = connect_db()
    transactions = conn.execute('''
        SELECT t.*, e.type_name
        FROM transactions t
        LEFT JOIN expense_types e ON t.type_id = e.id
        ORDER BY t.date DESC
    ''').fetchall()
    conn.close()

    si = StringIO()
    cw = csv.writer(si)

    # UTF-8 ile BOM eklemek (Excel'de Türkçe karakterlerin doğru görüntülenmesi için)
    si.write('\ufeff')

    # CSV Başlıkları
    cw.writerow(['ID', 'Açıklama', 'Miktar (TL)', 'Tarih', 'Tür'])

    # Her işlemi ayrı sütunlara yaz
    for txn in transactions:
        formatted_amount = "{:+,.2f}".format(float(txn['amount']))  # Miktarı iki ondalık basamakla formatla
        formatted_date = datetime.strptime(txn['date'], '%Y-%m-%d').strftime('%d-%m-%Y')  # Tarihi dd-mm-yyyy formatına çevir
        cw.writerow([txn['id'], txn['description'], formatted_amount, formatted_date, txn['type_name']])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=transactions.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

# İşlem silme
@app.route('/delete_transaction/<int:transaction_id>', methods=['POST'])
def delete_transaction(transaction_id):
    conn = connect_db()
    transaction = conn.execute('SELECT amount FROM transactions WHERE id = ?', (transaction_id,)).fetchone()

    if transaction:
        amount = transaction['amount']
        conn.execute('DELETE FROM transactions WHERE id = ?', (transaction_id,))
        conn.execute('UPDATE balance SET total = total - ? WHERE id = 1', (amount,))
        conn.commit()

    conn.close()
    return redirect('/')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0')
